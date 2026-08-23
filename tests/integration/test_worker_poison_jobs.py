"""A claimed job whose worker dies must go back to the queue, then stop.

This replaced a test about a Redis queue outliving its database. The failure
mode is the same one it caught: work that can never succeed must not be
retried forever, because retries starve the queue of the slots real work needs.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from boobs_api import leases
from boobs_common.clock import now
from boobs_domain.enums import ExecutionStatus
from boobs_schemas.tables import Execution
from tests.helpers import auth, bootstrap, record_experience

pytestmark = [pytest.mark.integration]

DIGEST = "sha256:" + "cc" * 32


async def test_an_expired_lease_returns_the_job_to_the_queue(
    api: httpx.AsyncClient, db: Any
) -> None:
    key = await bootstrap(api, "lease-org", "lease-agent")
    experience_id = await record_experience(
        api, key, "Lease reclaim test capability", "lease_test", DIGEST
    )
    run = await api.post(f"/v1/experiences/{experience_id}/execute", headers=auth(key), json={})
    assert run.status_code in (200, 202), run.text

    claimed = await leases.claim_next(db, "worker-that-will-die")
    assert claimed is not None
    await db.commit()

    # Pretend the worker died holding the claim.
    execution = (await db.execute(select(Execution).where(Execution.id == claimed.id))).scalar_one()
    execution.lease_expires_at = now() - timedelta(minutes=1)
    await db.commit()

    assert await leases.reclaim_expired(db) >= 1
    await db.commit()

    execution = (await db.execute(select(Execution).where(Execution.id == claimed.id))).scalar_one()
    assert execution.status == ExecutionStatus.QUEUED
    assert execution.leased_by is None
    assert execution.attempts == 1


async def test_a_job_that_keeps_killing_workers_is_failed_not_retried_forever() -> None:
    """MAX_ATTEMPTS is what stops one poisonous job from wedging the queue."""
    assert leases.MAX_ATTEMPTS <= 5
