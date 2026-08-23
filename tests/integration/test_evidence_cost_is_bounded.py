"""Evidence must cost the same on run ten thousand as on run ten.

`recompute` refetched every terminal execution row for a version and re-scanned
its verifications on every call, and it is called inside the request path twice
per run -- from `report_result` and from `verify_execution`. So the price of
recording a run grew with how many runs there had already been, and a
capability was charged most exactly when it was succeeding most. Flagged in two
audits and still there (DECISIONS 57).

The fix must not cost the invariant decision 11 states: the numbers are
derivable from immutable rows and are never a counter somebody hopes is right.
Both halves are asserted here, and neither is asserted by claim:

* **Identical.** The folded answer and a full rescan of the same history are
  compared field by field. If they ever disagree, the fold is wrong and this
  fails -- that is what makes the checkpoint a cache rather than a source.
* **Bounded.** Measured, on a real history, against a real database, in rows
  read rather than in milliseconds: a fold over two thousand runs must read
  exactly as many rows as a fold over fifty, while the rescan it replaced is
  seen to read the whole difference.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from boobs_common import ids
from boobs_common.clock import now
from boobs_domain.enums import (
    ExecutionStatus,
    ExperienceStatus,
    VerificationLevel,
    Visibility,
)
from boobs_reputation.evidence import as_dict, rebuild, recompute
from boobs_schemas.tables import (
    Agent,
    Artifact,
    Execution,
    Experience,
    ExperienceVersion,
    Organization,
    Verification,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("docker")]

SHORT = 50
LONG = 2000

# The most rows one new run is allowed to make `recompute` read, whatever the
# history behind it. Generous by an order of magnitude against what the fold
# actually reads, because the exact figure is an implementation detail and
# "does not grow with the history" is the property being defended.
BOUNDED = 50


async def _seed(db: AsyncSession, runs: int) -> ExperienceVersion:
    """One version with `runs` finished executions, two organizations, one in
    six of them failing -- enough history to notice a linear scan in."""
    organizations = []
    for name in ("author", "corroborator"):
        org = Organization(id=ids.new_id(ids.ORGANIZATION), name=name, created_at=now())
        agent = Agent(
            id=ids.new_id(ids.AGENT),
            organization_id=org.id,
            name=f"{name}-agent",
            created_at=now(),
        )
        for row in (org, agent):
            db.add(row)
            await db.flush()
        organizations.append((org.id, agent.id))

    digest = "sha256:" + uuid.uuid4().hex + uuid.uuid4().hex
    artifact = Artifact(
        id=ids.new_id(ids.ARTIFACT),
        type="oci",
        reference=f"registry.test/80085/popular@{digest}",
        digest=digest,
        registered_by=organizations[0][1],
        created_at=now(),
    )
    experience = Experience(
        id=ids.new_id(ids.EXPERIENCE),
        organization_id=organizations[0][0],
        goal_statement="a capability everybody uses",
        goal_intent="popular",
        tags=[],
        status=ExperienceStatus.CANDIDATE,
        verification_level=VerificationLevel.UNVERIFIED,
        visibility=Visibility.PUBLIC,
        latest_version=1,
        created_by=organizations[0][1],
        created_at=now(),
        updated_at=now(),
    )
    version = ExperienceVersion(
        id=ids.new_id(ids.VERSION),
        experience_id=experience.id,
        organization_id=organizations[0][0],
        version=1,
        artifact_id=artifact.id,
        command=["/bin/true"],
        verification={"verifier": "exit_code", "config": {}},
        lineage={},
        search_text="a capability everybody uses",
        created_by=organizations[0][1],
        created_at=now(),
    )
    for row in (artifact, experience, version):
        db.add(row)
        await db.flush()

    start = now() - timedelta(seconds=runs + 10)
    for index in range(runs):
        await _run(db, version, organizations[index % 2], index % 6 != 0, start, index)
    await db.flush()
    return version


async def _run(
    db: AsyncSession,
    version: ExperienceVersion,
    owner: tuple[str, str],
    worked: bool,
    start: Any,
    index: int,
) -> None:
    moment = start + timedelta(seconds=index)
    execution = Execution(
        id=ids.new_id(ids.EXECUTION),
        organization_id=owner[0],
        agent_id=owner[1],
        experience_id=version.experience_id,
        experience_version_id=version.id,
        artifact_digest="sha256:" + "ab" * 32,
        status=ExecutionStatus.SUCCEEDED if worked else ExecutionStatus.FAILED,
        exit_code=0 if worked else 1,
        duration_ms=20 + index % 90,
        error=None if worked else "upstream changed its format",
        started_at=moment,
        completed_at=moment,
        created_at=moment,
    )
    db.add(execution)
    if worked:
        db.add(
            Verification(
                id=ids.new_id(ids.VERIFICATION),
                execution_id=execution.id,
                experience_version_id=version.id,
                verifier="exit_code",
                passed=True,
                level=VerificationLevel.CLAIMED,
                detail={"exit_code": 0},
                created_at=moment,
            )
        )


class Counting:
    """A session that counts every row the code under test pulls out of Postgres.

    Rows, not milliseconds. A wall clock on this machine is mostly round trips
    -- both paths pay six of them and neither can go below that floor, which
    made a timing ratio a measurement of Docker's network stack as much as of
    the code. Rows read is the thing that actually grew with the history, it is
    the same number on every machine, and it is exact.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.rows = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)

    async def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        result = await self._session.execute(statement, *args, **kwargs)
        # ORM results do not carry `returns_rows`; only the cursor results a
        # write produces do, and those are the ones with nothing to count.
        if not getattr(result, "returns_rows", True):
            return result
        frozen = result.freeze()
        self.rows += len(frozen().all())
        return frozen()


async def _rows_to_fold(db: AsyncSession, version: ExperienceVersion) -> int:
    """Report one more run, recompute, and count what recompute had to read."""
    await _run(db, version, (version.organization_id, version.created_by), True, now(), 0)
    await db.flush()
    counting = Counting(db)
    await recompute(counting, version.id)  # type: ignore[arg-type]
    return counting.rows


async def _rows_to_rescan(db: AsyncSession, version: ExperienceVersion) -> int:
    counting = Counting(db)
    await rebuild(counting, version.id)  # type: ignore[arg-type]
    return counting.rows


async def test_a_fold_and_a_rescan_produce_the_same_numbers(db: AsyncSession) -> None:
    """The invariant decision 11 states, asserted rather than argued.

    A checkpoint is only a cache if throwing it away changes nothing. Two
    thousand runs of real history, folded one at a time, then rebuilt from the
    immutable rows: every field must match.
    """
    version = await _seed(db, LONG)
    await rebuild(db, version.id)
    for offset in range(5):
        await _run(db, version, (version.organization_id, version.created_by), True, now(), offset)
        await db.flush()
        folded = await recompute(db, version.id)

    numbers = as_dict(folded)
    level, median_ms = folded.verification_level, folded.median_duration_ms

    counting = Counting(db)
    rescanned = await rebuild(counting, version.id)  # type: ignore[arg-type]

    # A rescan that quietly folded instead would make this test pass by
    # comparing the fold with itself, so it is asked to prove it read the
    # history before its answer is believed.
    assert counting.rows > LONG, f"the rescan only read {counting.rows} rows"
    assert as_dict(rescanned) == numbers
    assert rescanned.verification_level == level
    assert rescanned.median_duration_ms == median_ms


async def test_recording_a_run_does_not_cost_the_whole_history(db: AsyncSession) -> None:
    """The defect, measured, with its own control.

    Two versions of the same shape, forty times the history apart. The rescan
    is the control -- it is what used to run inside the request, and it must be
    seen to grow, or this test is measuring nothing. The fold is the claim, and
    the claim is not "smaller": it is that the number does not move at all
    between fifty runs of history and two thousand.
    """
    short = await _seed(db, SHORT)
    long = await _seed(db, LONG)
    await rebuild(db, short.id)
    await rebuild(db, long.id)

    # The control. A rescan reads every execution and every verification, so
    # the extra history has to show up here row for row.
    grew = await _rows_to_rescan(db, long) - await _rows_to_rescan(db, short)
    assert grew >= LONG - SHORT, f"the rescan did not read the extra history ({grew} rows)"

    over_short = await _rows_to_fold(db, short)
    over_long = await _rows_to_fold(db, long)

    assert over_long == over_short, (
        f"a fold read {over_long} rows against {LONG} runs of history and {over_short} "
        f"against {SHORT} -- the request path is still paying for the history"
    )
    # And it is a handful, not a page: the stat row, the run that just
    # finished, its verification, the Experience being graded, and the stat row
    # read back. Loosely bounded on purpose -- the exact figure is an
    # implementation detail, "does not grow" is not.
    assert over_long <= BOUNDED, f"a fold read {over_long} rows for one new run"
