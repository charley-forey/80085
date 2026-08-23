"""The sweep that runs when nothing else does.

`recompute` re-evaluates a version when a run is reported. A capability that
broke and that nobody has run since gets no such call, and it is exactly the
one still sitting in recall telling agents to use it -- so spec section 24 asks
for a clock as well as a trigger. This is the clock, against real rows: no
recompute, no request, just the job.

It is also the reconciliation half of decision 57. The job runs the full
rescan, not the fold, so a checkpoint that had drifted for any reason is
corrected without anybody having noticed it had.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from boobs_api import scheduler
from boobs_common import ids
from boobs_common.clock import now
from boobs_domain.enums import (
    ExecutionStatus,
    ExperienceStatus,
    VerificationLevel,
    Visibility,
)
from boobs_schemas import db as database
from boobs_schemas.tables import (
    Agent,
    Artifact,
    Execution,
    ExecutionStat,
    Experience,
    ExperienceVersion,
    Organization,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("docker")]


async def test_the_sweep_withdraws_what_rotted_while_nobody_was_looking(
    db: AsyncSession,
) -> None:
    org = Organization(id=ids.new_id(ids.ORGANIZATION), name="sweep", created_at=now())
    agent = Agent(
        id=ids.new_id(ids.AGENT), organization_id=org.id, name="sweep-agent", created_at=now()
    )
    digest = "sha256:" + uuid.uuid4().hex + uuid.uuid4().hex
    artifact = Artifact(
        id=ids.new_id(ids.ARTIFACT),
        type="oci",
        reference=f"registry.test/80085/swept@{digest}",
        digest=digest,
        registered_by=agent.id,
        created_at=now(),
    )
    experience = Experience(
        id=ids.new_id(ids.EXPERIENCE),
        organization_id=org.id,
        goal_statement="something that used to work",
        goal_intent="rotted",
        tags=[],
        status=ExperienceStatus.VERIFIED,
        verification_level=VerificationLevel.CLAIMED,
        visibility=Visibility.PUBLIC,
        latest_version=1,
        created_by=agent.id,
        created_at=now(),
        updated_at=now(),
    )
    version = ExperienceVersion(
        id=ids.new_id(ids.VERSION),
        experience_id=experience.id,
        organization_id=org.id,
        version=1,
        artifact_id=artifact.id,
        command=["/bin/true"],
        verification={"verifier": "exit_code", "config": {}},
        lineage={},
        search_text="something that used to work",
        created_by=agent.id,
        created_at=now(),
    )
    for row in (org, agent, artifact, experience, version):
        db.add(row)
        await db.flush()

    moment = now() - timedelta(hours=2)
    for index in range(10):
        db.add(
            Execution(
                id=ids.new_id(ids.EXECUTION),
                organization_id=org.id,
                agent_id=agent.id,
                experience_id=experience.id,
                experience_version_id=version.id,
                artifact_digest="sha256:" + "ab" * 32,
                status=ExecutionStatus.FAILED,
                exit_code=1,
                duration_ms=10,
                error="the upstream API returned 410",
                started_at=moment + timedelta(seconds=index),
                completed_at=moment + timedelta(seconds=index),
                created_at=moment + timedelta(seconds=index),
            )
        )
    # The stat row exists and is stale, which is the state a version is left in
    # when it stopped being run: nothing has called recompute since the runs
    # that broke it.
    db.add(
        ExecutionStat(
            experience_version_id=version.id,
            experience_id=experience.id,
            successful_runs=40,
            failed_runs=0,
            success_rate=1.0,
            confidence=0.9,
            distinct_organizations=2,
            verification_level=VerificationLevel.CLAIMED,
            failure_modes={},
            updated_at=now() - timedelta(days=30),
        )
    )
    await db.commit()
    # `run` disposes the engine, as a cron process must. Let go of this session
    # first rather than leaving the fixture holding a dead pool.
    experience_id, version_id = experience.id, version.id
    await db.close()

    swept = await scheduler.run("evidence")

    assert swept >= 1
    async with database.session() as session:
        status = (
            await session.execute(select(Experience.status).where(Experience.id == experience_id))
        ).scalar_one()
        stat: Any = (
            await session.execute(
                select(ExecutionStat).where(ExecutionStat.experience_version_id == version_id)
            )
        ).scalar_one()

    assert status == ExperienceStatus.QUARANTINED
    # The stale numbers are corrected from the immutable rows, not trusted.
    assert stat.successful_runs == 0
    assert stat.failed_runs == 10
    assert stat.checkpoint is not None
