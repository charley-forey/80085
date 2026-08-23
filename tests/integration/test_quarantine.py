"""What rots stops being recommended, and what recovers comes back.

Spec section 24 asked for both halves and the corpus only ever had one:
promotion was a ratchet, so an Experience that reached `verified` and then
started failing every run stayed `verified` and kept being handed out. These
run the real `recompute` against real rows and then ask the real recall filter
whether the thing is still on offer, because "quarantined" is worth nothing as
a column value -- it is worth something only if it takes the capability out of
what agents are given (DECISIONS 56).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from boobs_common import ids
from boobs_common.clock import now
from boobs_domain.enums import (
    ExecutionStatus,
    ExperienceStatus,
    VerificationLevel,
    Visibility,
)
from boobs_domain.protocols import Principal, RecallQuery
from boobs_reputation.evidence import QUARANTINE_WINDOW, quarantine, recompute
from boobs_retrieval.pipeline import base_query
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

ANYONE = Principal(organization_id="org_reader", agent_id="agt_reader")


async def _organization(db: AsyncSession, name: str) -> tuple[str, str]:
    org = Organization(id=ids.new_id(ids.ORGANIZATION), name=name, created_at=now())
    agent = Agent(
        id=ids.new_id(ids.AGENT), organization_id=org.id, name=f"{name}-agent", created_at=now()
    )
    for row in (org, agent):
        db.add(row)
        await db.flush()
    return org.id, agent.id


async def _experience(db: AsyncSession, org_id: str, agent_id: str) -> ExperienceVersion:
    digest = "sha256:" + uuid.uuid4().hex + uuid.uuid4().hex
    artifact = Artifact(
        id=ids.new_id(ids.ARTIFACT),
        type="oci",
        reference=f"registry.test/80085/rots@{digest}",
        digest=digest,
        registered_by=agent_id,
        created_at=now(),
    )
    experience = Experience(
        id=ids.new_id(ids.EXPERIENCE),
        organization_id=org_id,
        goal_statement="convert a spreadsheet into json",
        goal_intent="convert_spreadsheet",
        tags=[],
        status=ExperienceStatus.CANDIDATE,
        verification_level=VerificationLevel.UNVERIFIED,
        visibility=Visibility.PUBLIC,
        latest_version=1,
        created_by=agent_id,
        created_at=now(),
        updated_at=now(),
    )
    version = ExperienceVersion(
        id=ids.new_id(ids.VERSION),
        experience_id=experience.id,
        organization_id=org_id,
        version=1,
        artifact_id=artifact.id,
        command=["/bin/true"],
        verification={"verifier": "exit_code", "config": {}},
        lineage={},
        search_text="convert a spreadsheet into json",
        created_by=agent_id,
        created_at=now(),
    )
    for row in (artifact, experience, version):
        db.add(row)
        await db.flush()
    return version


_tick = 0


async def _run(
    db: AsyncSession,
    version: ExperienceVersion,
    org_id: str,
    agent_id: str,
    worked: bool,
) -> None:
    """One terminal execution, with a passing verification when it worked.

    Each run gets its own instant, a second apart, because that is what real
    runs have and because a thousand rows sharing one timestamp is the shape
    the checkpoint deliberately refuses (see `BOUNDARY_LIMIT`).
    """
    global _tick
    _tick += 1
    moment = now() + timedelta(seconds=_tick)
    execution = Execution(
        id=ids.new_id(ids.EXECUTION),
        organization_id=org_id,
        agent_id=agent_id,
        experience_id=version.experience_id,
        experience_version_id=version.id,
        artifact_digest="sha256:" + "ab" * 32,
        status=ExecutionStatus.SUCCEEDED if worked else ExecutionStatus.FAILED,
        exit_code=0 if worked else 1,
        duration_ms=25,
        error=None if worked else "the input format changed",
        started_at=moment,
        completed_at=moment,
        created_at=moment,
    )
    db.add(execution)
    await db.flush()
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
        await db.flush()


async def _status(db: AsyncSession, experience_id: str) -> Any:
    return (
        await db.execute(select(Experience.status).where(Experience.id == experience_id))
    ).scalar_one()


async def _recallable(db: AsyncSession, version: ExperienceVersion) -> bool:
    """Would recall's hard filters still offer this version to anyone?

    The real `base_query`, not a re-implementation of it: a status nothing acts
    on is a column value, and the whole point of quarantine is that the
    capability stops being handed out.
    """
    rows = (
        await db.execute(
            base_query(ANYONE, RecallQuery(task="convert a spreadsheet into json")).where(
                ExperienceVersion.id == version.id
            )
        )
    ).all()
    return bool(rows)


async def _proven(db: AsyncSession) -> tuple[ExperienceVersion, tuple[str, str], tuple[str, str]]:
    """A verified capability, corroborated by two organizations, that works."""
    author = await _organization(db, "author")
    other = await _organization(db, "corroborator")
    version = await _experience(db, *author)
    for _ in range(3):
        await _run(db, version, *author, worked=True)
        await _run(db, version, *other, worked=True)
    await recompute(db, version.id)
    assert await _status(db, version.experience_id) == ExperienceStatus.VERIFIED
    return version, author, other


async def test_a_capability_that_starts_failing_stops_being_recommended(
    db: AsyncSession,
) -> None:
    """The missing half of the ratchet, end to end.

    Six proven runs across two organizations is a `verified` Experience with a
    100% lifetime success rate. Twenty failures later the lifetime rate is
    still 23%, which is exactly why the policy reads the recent window and not
    the total.
    """
    version, author, _ = await _proven(db)
    assert await _recallable(db, version)

    for _ in range(QUARANTINE_WINDOW):
        await _run(db, version, *author, worked=False)
    stat = await recompute(db, version.id)

    assert await _status(db, version.experience_id) == ExperienceStatus.QUARANTINED
    assert not await _recallable(db, version), "a quarantined capability is still being offered"
    # The successes are not deleted or disbelieved -- they happened. What
    # changed is what the corpus does about them.
    assert stat.successful_runs == 6

    reason = (
        await db.execute(
            select(Experience.quarantine).where(Experience.id == version.experience_id)
        )
    ).scalar_one()
    assert reason["manual"] is False
    assert reason["by"] == "evidence"
    assert "failed" in reason["reason"]


async def test_one_bad_afternoon_does_not_withdraw_anything(db: AsyncSession) -> None:
    """Recall's answer must not depend on the minute you asked it.

    Failures are added one at a time and the status is checked after every
    single one, which is the thrash a naive threshold produces: the run that
    crosses it flips the Experience, the next success flips it back.
    """
    version, author, other = await _proven(db)
    flips = 0
    previous = await _status(db, version.experience_id)
    for index in range(QUARANTINE_WINDOW):
        # Two in three fail: bad, sustained, and still under the threshold.
        await _run(db, version, *author, worked=index % 3 == 0)
        await recompute(db, version.id)
        current = await _status(db, version.experience_id)
        flips += current != previous
        previous = current
    assert previous == ExperienceStatus.VERIFIED
    assert flips == 0, "a capability that never crossed the threshold changed status anyway"


async def test_a_capability_that_recovers_comes_back(db: AsyncSession) -> None:
    """A corpus that can only lose entries decays. This is the way out.

    A quarantined Experience is still executable by its exact id -- only recall
    withdraws it -- so the way back is the same way in: run it, and let the
    runs say so. It returns to `candidate`, not to `verified`: corroboration is
    re-earned through the ordinary path.
    """
    version, author, other = await _proven(db)
    for _ in range(QUARANTINE_WINDOW):
        await _run(db, version, *author, worked=False)
    await recompute(db, version.id)
    assert await _status(db, version.experience_id) == ExperienceStatus.QUARANTINED

    # Halfway back is still quarantined: the hysteresis gap is the point.
    for _ in range(QUARANTINE_WINDOW // 2):
        await _run(db, version, *author, worked=True)
    await recompute(db, version.id)
    assert await _status(db, version.experience_id) == ExperienceStatus.QUARANTINED
    assert not await _recallable(db, version)

    for _ in range(QUARANTINE_WINDOW):
        await _run(db, version, *other, worked=True)
    await recompute(db, version.id)

    assert await _status(db, version.experience_id) == ExperienceStatus.VERIFIED
    assert await _recallable(db, version)
    assert (
        await db.execute(
            select(Experience.quarantine).where(Experience.id == version.experience_id)
        )
    ).scalar_one() is None


async def test_an_operators_withdrawal_is_not_undone_by_a_good_run(db: AsyncSession) -> None:
    """The reasons a person quarantines something are not failures.

    A credential baked into an image, a licence problem, an artifact doing
    something nobody wants done: all of them run perfectly. If a run of
    successes released those, the endpoint would be decorative.
    """
    version, author, other = await _proven(db)
    experience = (
        await db.execute(select(Experience).where(Experience.id == version.experience_id))
    ).scalar_one()
    quarantine(experience, reason="ships a live API key", by="agt_operator", manual=True)
    await db.flush()

    for _ in range(QUARANTINE_WINDOW * 2):
        await _run(db, version, *author, worked=True)
        await _run(db, version, *other, worked=True)
    await recompute(db, version.id)

    assert await _status(db, version.experience_id) == ExperienceStatus.QUARANTINED
    assert not await _recallable(db, version)


async def test_an_old_version_rotting_does_not_withdraw_the_current_one(
    db: AsyncSession,
) -> None:
    """Recall only ever offers the current version, so only it gets a vote.

    Withdrawing the Experience because a version nobody is handed has stopped
    working would punish exactly the fix that was published to replace it.
    """
    version, author, other = await _proven(db)
    experience = (
        await db.execute(select(Experience).where(Experience.id == version.experience_id))
    ).scalar_one()
    successor = ExperienceVersion(
        id=ids.new_id(ids.VERSION),
        experience_id=experience.id,
        organization_id=experience.organization_id,
        version=2,
        artifact_id=version.artifact_id,
        command=["/bin/true"],
        verification={"verifier": "exit_code", "config": {}},
        lineage={},
        search_text="convert a spreadsheet into json",
        created_by=author[1],
        created_at=now(),
    )
    db.add(successor)
    experience.latest_version = 2
    await db.flush()

    for _ in range(QUARANTINE_WINDOW):
        await _run(db, version, *author, worked=False)
    await recompute(db, version.id)

    assert await _status(db, experience.id) == ExperienceStatus.VERIFIED
