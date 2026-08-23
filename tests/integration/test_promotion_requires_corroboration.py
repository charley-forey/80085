"""Promotion to VERIFIED is the claim the whole product rests on.

The unit tests pin the arithmetic. This one pins the wiring: real rows, the
real `recompute`, and the real triggers that make those rows immutable.
"""

from __future__ import annotations

import uuid
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
from boobs_reputation.evidence import recompute
from boobs_schemas.tables import (
    Agent,
    Artifact,
    Execution,
    Experience,
    ExperienceVersion,
    Organization,
    Verification,
)

pytestmark = [pytest.mark.integration]


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
        reference=f"registry.test/80085/self-attested@{digest}",
        digest=digest,
        registered_by=agent_id,
        created_at=now(),
    )
    experience = Experience(
        id=ids.new_id(ids.EXPERIENCE),
        organization_id=org_id,
        goal_statement="exit zero, convincingly",
        goal_intent="self_attest",
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
        search_text="exit zero convincingly",
        created_by=agent_id,
        created_at=now(),
    )
    for row in (artifact, experience, version):
        db.add(row)
        await db.flush()
    return version


async def _successful_run(
    db: AsyncSession,
    version: ExperienceVersion,
    org_id: str,
    agent_id: str,
    level: VerificationLevel = VerificationLevel.CLAIMED,
) -> None:
    execution = Execution(
        id=ids.new_id(ids.EXECUTION),
        organization_id=org_id,
        agent_id=agent_id,
        experience_id=version.experience_id,
        experience_version_id=version.id,
        artifact_digest="sha256:" + "ab" * 32,
        status=ExecutionStatus.SUCCEEDED,
        exit_code=0,
        duration_ms=25,
        started_at=now(),
        completed_at=now(),
        created_at=now(),
    )
    db.add(execution)
    await db.flush()
    db.add(
        Verification(
            id=ids.new_id(ids.VERIFICATION),
            execution_id=execution.id,
            experience_version_id=version.id,
            verifier="exit_code",
            passed=True,
            level=level,
            detail={"exit_code": 0},
            created_at=now(),
        )
    )
    await db.flush()


async def _status(db: AsyncSession, experience_id: str) -> Any:
    return (
        await db.execute(select(Experience.status).where(Experience.id == experience_id))
    ).scalar_one()


async def test_one_organization_cannot_promote_its_own_experience(db: AsyncSession) -> None:
    """The audit's attack, run for real: record it, run it, run it again."""
    org_id, agent_id = await _organization(db, "self-attester")
    version = await _experience(db, org_id, agent_id)

    for _ in range(25):
        await _successful_run(db, version, org_id, agent_id)
    stat = await recompute(db, version.id)

    assert stat.successful_runs == 25
    assert stat.distinct_organizations == 1
    assert await _status(db, version.experience_id) == ExperienceStatus.CANDIDATE
    # Twenty-five self-runs cap at ten, and an exit code is only a claim.
    assert stat.confidence < 0.5


async def test_a_second_organization_promotes_it(db: AsyncSession) -> None:
    author_org, author_agent = await _organization(db, "author")
    other_org, other_agent = await _organization(db, "corroborator")
    version = await _experience(db, author_org, author_agent)

    await _successful_run(db, version, author_org, author_agent)
    await recompute(db, version.id)
    assert await _status(db, version.experience_id) == ExperienceStatus.CANDIDATE

    await _successful_run(db, version, other_org, other_agent)
    stat = await recompute(db, version.id)

    assert stat.distinct_organizations == 2
    assert await _status(db, version.experience_id) == ExperienceStatus.VERIFIED
    # Proven only by exit codes, so it says "claimed" rather than "proven".
    assert stat.verification_level == VerificationLevel.CLAIMED
    level = (
        await db.execute(
            select(Experience.verification_level).where(Experience.id == version.experience_id)
        )
    ).scalar_one()
    assert level == VerificationLevel.CLAIMED
