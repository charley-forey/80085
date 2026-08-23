"""No handler may talk to object storage with a database transaction open.

get_db keeps one transaction open for the whole request, so an S3 round trip
made mid-handler pins a Postgres connection for its duration. The pool is ten
plus ten overflow per process: a burst of concurrent leases or results empties
it while the CPU is idle, and a slow bucket presents as a database outage.

These are ordering tests, not timing tests. The fake session records when a
transaction is open, the fake bucket records what it saw, and the assertion is
that the two never overlap -- which is the property, stated exactly.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import Response
from sqlalchemy import Update
from starlette.requests import Request

from boobs_api import routes, worker_routes
from boobs_common import storage
from boobs_domain.enums import ExecutionStatus, ExperienceStatus, Visibility
from boobs_domain.protocols import Principal
from boobs_schemas.api import ExecuteRequest
from boobs_schemas.tables import Artifact, Execution, Experience, ExperienceVersion
from boobs_security.keys import Scope

ORG = "org_boundaries"
DIGEST = "sha256:" + "ab" * 32


class Rows:
    """A result set with the accessors the handlers use."""

    def __init__(self, row: Any) -> None:
        self._row = row

    def scalar_one(self) -> Any:
        return self._row

    def scalar_one_or_none(self) -> Any:
        return self._row

    def scalars(self) -> Rows:
        return self

    def all(self) -> list[Any]:
        return [] if self._row is None else [self._row]


class RecordingSession:
    """Enough AsyncSession for a handler to run, plus the fact under test.

    `log` is the ordered story of the request: every database touch, every
    commit, and every object-storage call annotated with whether a transaction
    was open when it happened.
    """

    def __init__(self, *results: Any) -> None:
        self._results = list(results)
        self.open = False
        self.log: list[str] = []
        self.statements: list[Any] = []

    async def execute(self, statement: Any = None, *_: Any, **__: Any) -> Rows:
        self.open = True
        self.log.append("query")
        self.statements.append(statement)
        return Rows(self._results.pop(0) if self._results else None)

    def add(self, _: Any) -> None:
        self.open = True
        self.log.append("write")

    async def flush(self) -> None:
        self.open = True
        self.log.append("write")

    async def commit(self) -> None:
        self.open = False
        self.log.append("commit")

    async def rollback(self) -> None:
        self.open = False
        self.log.append("rollback")


class Bucket:
    """Stands in for S3, and reports the transaction state it was called in."""

    def __init__(self, db: RecordingSession, payload: Any = None) -> None:
        self._db = db
        self._payload = payload if payload is not None else {}

    async def put_json(self, key: str, _: dict[str, Any]) -> str:
        self._db.log.append(f"storage:{'IN-TRANSACTION' if self._db.open else 'released'}")
        return key

    async def get_json(self, _: str) -> Any:
        self._db.log.append(f"storage:{'IN-TRANSACTION' if self._db.open else 'released'}")
        return self._payload


def use_bucket(monkeypatch: pytest.MonkeyPatch, bucket: Bucket) -> None:
    monkeypatch.setattr(storage, "put_json", bucket.put_json)
    monkeypatch.setattr(storage, "get_json", bucket.get_json)


def assert_never_in_transaction(log: list[str]) -> None:
    touches = [entry for entry in log if entry.startswith("storage:")]
    assert touches, f"no object-storage call was made at all: {log}"
    assert all(entry == "storage:released" for entry in touches), log


# --------------------------------------------------------------------- fixtures


def an_experience() -> Experience:
    return Experience(
        id="exp_boundaries",
        organization_id=ORG,
        goal_statement="Convert a CSV file into a JSON array",
        goal_intent="csv_to_json",
        tags=[],
        status=ExperienceStatus.CANDIDATE,
        visibility=Visibility.PUBLIC,
        latest_version=1,
        created_by="agt_boundaries",
    )


def a_version() -> ExperienceVersion:
    return ExperienceVersion(
        id="ver_boundaries",
        experience_id="exp_boundaries",
        organization_id=ORG,
        version=1,
        artifact_id="art_boundaries",
        command=["python", "/app/main.py"],
        verification=None,
        requires_network=False,
        search_text="csv to json",
        created_by="agt_boundaries",
    )


def an_artifact() -> Artifact:
    return Artifact(
        id="art_boundaries",
        reference=f"registry.test/80085/demo@{DIGEST}",
        digest=DIGEST,
    )


def a_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 5000),
        }
    )


class NoEvents:
    """The event store, minus the database."""

    def __init__(self, _: Any) -> None: ...

    async def append(self, *_: Any, **__: Any) -> None: ...


# ---------------------------------------------------------------------- execute


async def test_execute_stages_inputs_outside_the_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """And stages them *before* the row, because the commit is the enqueue.

    A worker can lease the row the instant it lands. If the inputs were not in
    the bucket yet it would run the artifact against nothing and the platform
    would record that as evidence.
    """
    # The rate limiter goes first: one statement to keep its commit off the
    # disk, one to count the hit. Then the idempotency lookup finds nothing.
    db = RecordingSession(None, 1, None)
    bucket = Bucket(db)
    use_bucket(monkeypatch, bucket)

    experience, version, artifact = an_experience(), a_version(), an_artifact()

    # The stubs still query, because the real ones do: it is those reads that
    # open the transaction the object-storage call must not be inside.
    class Experiences:
        def __init__(self, db: RecordingSession) -> None:
            self.db = db

        async def get(self, *_: Any) -> Experience:
            await self.db.execute()
            return experience

        async def get_version(self, *_: Any) -> ExperienceVersion:
            await self.db.execute()
            return version

    class Artifacts:
        def __init__(self, db: RecordingSession) -> None:
            self.db = db

        async def resolve(self, _: str) -> Artifact:
            await self.db.execute()
            return artifact

    class Nothing:
        async def authorize(self, *_: Any, **__: Any) -> None: ...

    class Queued:
        status = ExecutionStatus.QUEUED

    monkeypatch.setattr(routes, "ExperienceRepository", Experiences)
    monkeypatch.setattr(routes, "ArtifactRepository", Artifacts)
    monkeypatch.setattr(routes, "policy", Nothing())
    monkeypatch.setattr(routes, "_execution_response", lambda *_: _resolved(Queued()))

    await routes.execute_experience(
        experience_id="exp_boundaries",
        request=ExecuteRequest(inputs={"data.csv": "YSxiCjEsMg=="}),
        http=a_request(),
        db=db,  # type: ignore[arg-type]
        principal=Principal(
            organization_id=ORG,
            agent_id="agt_boundaries",
            scopes=frozenset({Scope.EXECUTIONS_RUN}),
        ),
        response=Response(),
    )

    assert_never_in_transaction(db.log)
    staged = db.log.index("storage:released")
    assert "write" not in db.log[:staged], f"the row was written before its inputs: {db.log}"


def _resolved(value: Any) -> Any:
    """A already-finished awaitable, so a plain lambda can stand in for a
    coroutine function."""

    async def wrapper() -> Any:
        return value

    return wrapper()


# ------------------------------------------------------------------------ lease


async def test_lease_commits_the_claim_before_reading_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """claim_next holds a row lock. Fetching inputs first would hold that lock,
    and a pooled connection, for a whole S3 round trip -- with every other
    worker polling the same queue behind it."""
    version, artifact = a_version(), an_artifact()
    db = RecordingSession(version, artifact)
    use_bucket(monkeypatch, Bucket(db, {"data.csv": "YSxiCjEsMg=="}))

    claimed = Execution(
        id="exe_boundaries",
        organization_id=ORG,
        agent_id="agt_boundaries",
        experience_id="exp_boundaries",
        experience_version_id="ver_boundaries",
        artifact_digest=DIGEST,
        status=ExecutionStatus.RUNNING,
        leased_by="worker-1",
    )

    async def claim(*_: Any, **__: Any) -> Execution:
        db.open = True
        db.log.append("query")
        return claimed

    async def depth(*_: Any) -> int:
        return 0

    monkeypatch.setattr(worker_routes.leases, "claim_next", claim)
    monkeypatch.setattr(worker_routes.leases, "depth", depth)
    monkeypatch.setattr(worker_routes, "SqlEventStore", NoEvents)

    response = await worker_routes.lease(
        request=worker_routes.LeaseRequest(worker_id="worker-1"),
        db=db,  # type: ignore[arg-type]
        principal=Principal(
            organization_id=ORG, agent_id="agt_boundaries", scopes=frozenset({Scope.WORKER})
        ),
    )

    assert response.job is not None
    assert response.job.inputs == {"data.csv": "YSxiCjEsMg=="}
    assert_never_in_transaction(db.log)


# ----------------------------------------------------------------------- result


async def test_result_uploads_before_it_records(monkeypatch: pytest.MonkeyPatch) -> None:
    """Outputs land in the bucket before output_key points at them.

    The other order would leave a row naming bytes that do not exist, and every
    later read of that execution would fail. This way a failure after the
    upload leaves an object nothing references, which nothing reads.
    """
    running = Execution(
        id="exe_boundaries",
        organization_id=ORG,
        agent_id="agt_boundaries",
        experience_id="exp_boundaries",
        experience_version_id="ver_boundaries",
        artifact_digest=DIGEST,
        status=ExecutionStatus.RUNNING,
        leased_by="worker-1",
    )
    # The third statement is the guarded UPDATE that records the run; it comes
    # back with the row id, meaning this worker still held the lease.
    db = RecordingSession(running, a_version(), running.id)
    use_bucket(monkeypatch, Bucket(db))

    async def no_recompute(*_: Any, **__: Any) -> None: ...

    monkeypatch.setattr(worker_routes, "SqlEventStore", NoEvents)
    monkeypatch.setattr(worker_routes, "recompute", no_recompute)

    await worker_routes.report_result(
        execution_id="exe_boundaries",
        request=worker_routes.ResultRequest(
            worker_id="worker-1",
            status=ExecutionStatus.SUCCEEDED,
            exit_code=0,
            duration_ms=12,
            outputs={"out.json": "e30="},
        ),
        db=db,  # type: ignore[arg-type]
        principal=Principal(
            organization_id=ORG, agent_id="agt_boundaries", scopes=frozenset({Scope.WORKER})
        ),
    )

    assert_never_in_transaction(db.log)
    uploaded = db.log.index("storage:released")
    assert "write" not in db.log[:uploaded], f"the row was written before the outputs: {db.log}"

    # And the key the row records is the one the bucket was just handed. The
    # write is a conditional UPDATE rather than an attribute assignment (see
    # DECISIONS.md 43), so the statement is where that shows.
    recorded = [statement for statement in db.statements if isinstance(statement, Update)]
    assert len(recorded) == 1, f"the run was recorded {len(recorded)} times: {db.log}"
    assert recorded[0].compile().params["output_key"] == storage.output_key("exe_boundaries")
