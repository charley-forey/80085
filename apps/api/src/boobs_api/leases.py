"""The execution queue, in Postgres.

`SELECT ... FOR UPDATE SKIP LOCKED` is a queue: exactly one worker claims each
row, concurrent claimers step over locked rows instead of blocking, and the
queue cannot drift from the execution history because they are the same table.

This replaced a Redis queue when the worker moved off-platform. A worker now
needs nothing but HTTPS to the API -- no database credentials, no queue
credentials, and no datastore exposed to the internet. See DECISIONS.md 17.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from boobs_common.clock import now
from boobs_domain.enums import ExecutionStatus
from boobs_observability import counter, gauge
from boobs_schemas.tables import Execution

# Two things nobody could see from outside: how much work is waiting, and how
# often a worker dies holding a claim. A rising reclaim rate is the signal that
# a worker is crashing on a particular artifact rather than merely being slow.
_depth = gauge("queue_depth", description="executions waiting for a worker")
_reclaims = counter("lease_reclaims", "expired leases, attributed by what happened to the row")

# How long a worker may hold a claim before it is assumed dead. Comfortably
# longer than the sandbox wall-clock limit plus image pull time.
DEFAULT_LEASE_SECONDS = 900

# A job that has been claimed this many times without ever reporting a result
# is not going to work. Failing it is kinder than retrying forever.
MAX_ATTEMPTS = 3


async def reclaim_expired(db: AsyncSession) -> int:
    """Return abandoned executions to the queue.

    A worker that crashes mid-run leaves a row marked running forever. Anything
    past its lease goes back to queued; anything that has burned through its
    attempts is failed with a reason, because silently retrying a job that
    kills its worker is how a queue wedges.
    """
    moment = now()
    expired = (
        await db.execute(
            select(Execution).where(
                Execution.status == ExecutionStatus.RUNNING,
                Execution.lease_expires_at.is_not(None),
                Execution.lease_expires_at < moment,
            )
        )
    ).scalars()

    reclaimed = 0
    for execution in expired:
        if execution.attempts >= MAX_ATTEMPTS:
            execution.status = ExecutionStatus.FAILED
            execution.error = f"abandoned after {execution.attempts} attempts without a result"
            execution.completed_at = moment
            _reclaims.add(1, {"outcome": "failed"})
        else:
            execution.status = ExecutionStatus.QUEUED
            execution.lease_expires_at = None
            execution.leased_by = None
            _reclaims.add(1, {"outcome": "requeued"})
        reclaimed += 1
    return reclaimed


async def claim_next(
    db: AsyncSession, worker_id: str, lease_seconds: int = DEFAULT_LEASE_SECONDS
) -> Execution | None:
    """Claim the oldest queued execution, or return None.

    SKIP LOCKED is what makes this safe with many workers: a row already being
    claimed by someone else is stepped over rather than waited on.
    """
    await reclaim_expired(db)

    candidate = (
        await db.execute(
            select(Execution.id)
            .where(Execution.status == ExecutionStatus.QUEUED)
            .order_by(Execution.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    ).scalar_one_or_none()

    if candidate is None:
        return None

    moment = now()
    await db.execute(
        update(Execution)
        .where(Execution.id == candidate)
        .values(
            status=ExecutionStatus.RUNNING,
            started_at=moment,
            leased_by=worker_id,
            lease_expires_at=moment + timedelta(seconds=lease_seconds),
            attempts=Execution.attempts + 1,
        )
    )
    return (await db.execute(select(Execution).where(Execution.id == candidate))).scalar_one()


async def depth(db: AsyncSession) -> int:
    """Queued executions waiting for a worker. Surfaced by /v1/ready so a
    deployment with no worker attached is visible rather than merely slow."""
    rows = (
        await db.execute(select(Execution.id).where(Execution.status == ExecutionStatus.QUEUED))
    ).scalars()
    queued = len(list(rows))
    # Sampled here rather than by a callback, because the callback would need a
    # database session of its own. /v1/ready and every lease call this, so an
    # attached worker or a probing platform keeps it fresh.
    _depth.set(queued)
    return queued
