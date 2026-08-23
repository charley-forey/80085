"""A result that arrives after the lease moved on must not land.

`report_result` checks the lease, then ends its transaction and spends an
unbounded amount of time outside the database: an upload, and a verifier that
may take as long as it likes. A lease is 900 seconds. A run slow enough to
outlive one is reclaimed underneath itself by `leases.claim_next` and handed to
a second worker -- and the first worker's write then arrives against a row that
is no longer its own.

Where that write lands decides how bad it is:

  * **The row is running again, claimed by B.** Nothing stops the write. A's
    stale SUCCEEDED becomes the recorded result, A's verification row becomes
    evidence `recompute` counts, and B's honest result is refused later by the
    append-only trigger. This is the corruption, and it is the first test here.
  * **The row is already terminal.** `executions_guard` refuses the UPDATE, so
    the transaction dies and worker A -- which did nothing wrong -- is answered
    with a 500. Postgres protects the data; nothing protects the worker.

These are ordering tests, not timing tests. The fake session holds the row the
way the database would and evaluates the handler's UPDATE against it -- WHERE
clause included -- so "the job changed hands while A's verifier was running" is
a sequence of function calls rather than a window to be raced. Under the
unguarded code the row ends up SUCCEEDED every time, not one time in twenty.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Update

from boobs_api import worker_routes
from boobs_common import storage
from boobs_common.errors import Forbidden
from boobs_domain.enums import ExecutionStatus, VerificationLevel
from boobs_domain.protocols import Principal
from boobs_schemas.tables import Execution, ExperienceVersion
from boobs_security.keys import Scope

ORG = "org_race"
DIGEST = "sha256:" + "cd" * 32
WORKER_A = "worker-a"
WORKER_B = "worker-b"


class Rows:
    def __init__(self, row: Any) -> None:
        self._row = row

    def scalar_one(self) -> Any:
        return self._row

    def scalar_one_or_none(self) -> Any:
        return self._row


class Database:
    """One executions row, and enough SQL to run the handler against it.

    `execute` dispatches on the statement rather than on call order, because
    the guarded handler and the unguarded one issue different sequences and
    both have to run against the same fake.
    """

    def __init__(self, row: Execution, version: ExperienceVersion) -> None:
        self.row = row
        self.version = version
        self.added: list[Any] = []
        self.log: list[str] = []

    async def execute(self, statement: Any, *_: Any, **__: Any) -> Rows:
        if isinstance(statement, Update):
            self.log.append("update")
            return Rows(self._update(statement))
        entity, column = _target(statement)
        self.log.append(f"select:{entity}.{column}")
        if entity == "Execution":
            return Rows(self.row if column == "Execution" else getattr(self.row, column))
        if entity == "ExperienceVersion":
            return Rows(self.version)
        return Rows(None)

    def _update(self, statement: Update) -> str | None:
        """Apply an UPDATE the way Postgres would: only if the WHERE matches.

        Compiled parameters carry both halves -- the SET values under their
        column names and the WHERE binds suffixed by the dialect -- so the
        guard being tested is evaluated rather than merely observed.
        """
        params = dict(statement.compile().params)
        criteria = {name[:-2]: value for name, value in params.items() if name.endswith("_1")}
        values = {name: value for name, value in params.items() if not name.endswith("_1")}
        if any(getattr(self.row, column) != value for column, value in criteria.items()):
            return None
        for column, value in values.items():
            setattr(self.row, column, value)
        return str(self.row.id)

    def add(self, row: Any) -> None:
        self.added.append(row)
        self.log.append(f"add:{type(row).__name__}")

    async def flush(self) -> None:
        self.log.append("flush")

    async def commit(self) -> None:
        self.log.append("commit")

    async def rollback(self) -> None:
        self.log.append("rollback")


def _target(statement: Any) -> tuple[str, str]:
    description = statement.column_descriptions[0]
    entity = description["entity"]
    return (entity.__name__ if entity is not None else ""), str(description["name"])


def a_row(status: str = ExecutionStatus.RUNNING, leased_by: str | None = WORKER_A) -> Execution:
    return Execution(
        id="exe_race",
        organization_id=ORG,
        agent_id="agt_race",
        experience_id="exp_race",
        experience_version_id="ver_race",
        artifact_digest=DIGEST,
        status=status,
        leased_by=leased_by,
        attempts=1,
    )


def a_version() -> ExperienceVersion:
    return ExperienceVersion(
        id="ver_race",
        experience_id="exp_race",
        organization_id=ORG,
        version=1,
        artifact_id="art_race",
        command=["python", "/app/main.py"],
        verification={"verifier": "json_schema", "config": {"file": "out.json", "schema": {}}},
        requires_network=False,
        search_text="race",
        created_by="agt_race",
    )


def a_principal() -> Principal:
    return Principal(organization_id=ORG, agent_id="agt_race", scopes=frozenset({Scope.WORKER}))


def a_result(worker_id: str = WORKER_A) -> worker_routes.ResultRequest:
    return worker_routes.ResultRequest(
        worker_id=worker_id,
        status=ExecutionStatus.SUCCEEDED,
        exit_code=0,
        duration_ms=1_000_000,
        outputs={"out.json": "e30="},
    )


class Events:
    """The event store, minus the database, remembering what it was asked to
    append -- because a discarded result must append nothing at all."""

    appended: list[str] = []

    def __init__(self, _: Any) -> None: ...

    async def append(self, _id: str, event_type: str, _payload: dict[str, Any]) -> None:
        Events.appended.append(str(event_type))


class Verdict:
    passed = True
    level = VerificationLevel.PROVEN
    detail: dict[str, Any] = {}


def setup(monkeypatch: pytest.MonkeyPatch, db: Database, on_verify: Any = None) -> list[str]:
    """Wire the handler to the fake session, and hand back the recompute log."""
    Events.appended = []
    recomputed: list[str] = []

    async def recompute(_db: Any, version_id: str) -> None:
        recomputed.append(version_id)

    async def put_json(key: str, _payload: Any) -> str:
        return key

    class Verifier:
        async def verify(self, *_: Any, **__: Any) -> Verdict:
            if on_verify is not None:
                on_verify()
            return Verdict()

    monkeypatch.setattr(storage, "put_json", put_json)
    monkeypatch.setattr(worker_routes, "SqlEventStore", Events)
    monkeypatch.setattr(worker_routes, "recompute", recompute)
    monkeypatch.setattr(worker_routes, "verifier", Verifier())
    return recomputed


async def test_a_stale_result_does_not_land_on_a_run_that_changed_hands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A's lease expires, B claims the job and is still running it, and A's slow
    verifier finally returns.

    Nothing in the database refuses this write: the row is `running`, which the
    append-only trigger allows. So A's SUCCEEDED becomes the recorded result of
    a run B is still executing, A's verification row becomes evidence, and B is
    refused when it reports what actually happened. Everything downstream of
    this row is recomputed from it, which is why this is the test that matters.
    """
    db = Database(a_row(), a_version())

    def the_job_changes_hands() -> None:
        # leases.claim_next, while A was verifying: the lease had expired, so
        # reclaim_expired returned the row to the queue and B claimed it.
        db.row.leased_by = WORKER_B
        db.row.attempts = 2
        db.row.lease_expires_at = None

    recomputed = setup(monkeypatch, db, on_verify=the_job_changes_hands)

    answer = await worker_routes.report_result(
        execution_id="exe_race",
        request=a_result(),
        db=db,  # type: ignore[arg-type]
        principal=a_principal(),
    )

    assert db.row.status == ExecutionStatus.RUNNING, (
        f"worker A recorded a result for a run it no longer holds: {db.row.status}"
    )
    assert db.row.exit_code is None
    assert db.row.output_key is None
    assert db.row.completed_at is None
    assert db.row.leased_by == WORKER_B

    # Nothing of A's survives anywhere else either. execution_events and
    # verifications are append-only, so a verdict written here could never be
    # taken back -- and recompute would count it.
    assert Events.appended == [], Events.appended
    assert db.added == [], db.added
    assert recomputed == []

    assert answer.accepted is False


async def test_a_result_for_a_run_someone_else_finished_is_told_so_not_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same lost lease, one step later: B has already recorded a failure.

    Here Postgres would defend itself -- `executions_guard` refuses an UPDATE
    to a terminal row -- so the unguarded handler does not corrupt anything, it
    just dies, and a worker that ran the job honestly is answered with a 500 it
    can neither fix nor retry. The guard turns that into the truth: your result
    was not needed, and here is the one that stands.
    """
    db = Database(a_row(), a_version())

    def worker_b_finishes_it() -> None:
        db.row.status = ExecutionStatus.FAILED
        db.row.leased_by = WORKER_B
        db.row.attempts = 2
        db.row.exit_code = 1
        db.row.logs_key = "logs/from-b"
        db.row.lease_expires_at = None

    recomputed = setup(monkeypatch, db, on_verify=worker_b_finishes_it)

    answer = await worker_routes.report_result(
        execution_id="exe_race",
        request=a_result(),
        db=db,  # type: ignore[arg-type]
        principal=a_principal(),
    )

    assert db.row.status == ExecutionStatus.FAILED
    assert db.row.exit_code == 1
    assert db.row.logs_key == "logs/from-b"
    assert Events.appended == [], Events.appended
    assert db.added == [], db.added
    assert recomputed == []

    assert answer.accepted is False
    assert answer.status == ExecutionStatus.FAILED
    assert answer.verified is None


async def test_a_worker_that_still_holds_its_lease_records_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the guard: a test that discarded everything would
    pass the one above and break the product."""
    db = Database(a_row(), a_version())
    recomputed = setup(monkeypatch, db)

    answer = await worker_routes.report_result(
        execution_id="exe_race",
        request=a_result(),
        db=db,  # type: ignore[arg-type]
        principal=a_principal(),
    )

    assert db.row.status == ExecutionStatus.SUCCEEDED
    assert db.row.exit_code == 0
    assert db.row.output_key == storage.output_key("exe_race")
    assert db.row.lease_expires_at is None
    assert Events.appended, "a recorded run must leave its events behind"
    assert [type(row).__name__ for row in db.added] == ["Verification"]
    assert recomputed == ["ver_race"]
    assert answer.accepted is True
    assert answer.verified is True
    assert answer.status == ExecutionStatus.SUCCEEDED
    assert db.log[-1] == "commit"


async def test_a_late_report_on_an_already_reclaimed_row_is_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same situation seen one step earlier: the row had already moved on when
    the report arrived. The answer is the same, and no work is done."""
    db = Database(a_row(status=ExecutionStatus.QUEUED, leased_by=None), a_version())
    recomputed = setup(monkeypatch, db)

    answer = await worker_routes.report_result(
        execution_id="exe_race",
        request=a_result(),
        db=db,  # type: ignore[arg-type]
        principal=a_principal(),
    )

    assert answer.accepted is False
    assert answer.status == ExecutionStatus.QUEUED
    assert Events.appended == []
    assert recomputed == []
    assert "update" not in db.log


async def test_a_worker_that_never_held_the_lease_is_still_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Losing a lease is forgiven; reporting on a stranger's running job is not.

    Both the polite answer and the guarded UPDATE key off the same fact -- who
    holds the lease now -- so this is the check they must not have replaced.
    """
    db = Database(a_row(leased_by=WORKER_B), a_version())
    setup(monkeypatch, db)

    with pytest.raises(Forbidden):
        await worker_routes.report_result(
            execution_id="exe_race",
            request=a_result(worker_id="thief"),
            db=db,  # type: ignore[arg-type]
            principal=a_principal(),
        )
