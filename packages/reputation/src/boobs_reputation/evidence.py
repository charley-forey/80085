"""Evidence and reputation (spec section 19).

Not a rating system. The only question is "will this probably work for me",
so every number here is recomputed from immutable execution and verification
rows and can be rebuilt from scratch at any time.

A run counts as *successful* only if the sandbox succeeded AND a verifier
passed. That is the whole distinction the product sells: an agent's claim is
not evidence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from boobs_common.clock import now
from boobs_domain.enums import ExecutionStatus, ExperienceStatus, VerificationLevel
from boobs_retrieval.ranking import wilson_lower_bound
from boobs_schemas.tables import Execution, ExecutionStat, Experience, Verification

TERMINAL = (
    ExecutionStatus.SUCCEEDED,
    ExecutionStatus.FAILED,
    ExecutionStatus.TIMEOUT,
    ExecutionStatus.REJECTED,
)


async def recompute(db: AsyncSession, experience_version_id: str) -> ExecutionStat:
    """Rebuild one version's evidence from source rows.

    Recomputing beats incrementing: counters cannot drift, and a replayed or
    corrected history produces the same numbers.
    """
    passed_ids = (
        select(Verification.execution_id)
        .where(
            Verification.experience_version_id == experience_version_id,
            Verification.passed.is_(True),
        )
        .scalar_subquery()
    )

    rows = (
        await db.execute(
            select(
                Execution.id,
                Execution.status,
                Execution.duration_ms,
                Execution.organization_id,
                Execution.error,
                Execution.id.in_(passed_ids).label("verified"),
            ).where(
                Execution.experience_version_id == experience_version_id,
                Execution.status.in_([s.value for s in TERMINAL]),
            )
        )
    ).all()

    successful_ids = {
        row.id for row in rows if row.verified and row.status == ExecutionStatus.SUCCEEDED
    }
    successful = [row for row in rows if row.id in successful_ids]
    failed = [row for row in rows if row.id not in successful_ids]

    durations = sorted(row.duration_ms for row in successful if row.duration_ms is not None)
    failure_modes: dict[str, int] = {}
    for row in failed:
        key = row.error or (
            "unverified" if row.status == ExecutionStatus.SUCCEEDED else str(row.status)
        )
        failure_modes[key] = failure_modes.get(key, 0) + 1

    last_verified = (
        await db.execute(
            select(func.max(Verification.created_at)).where(
                Verification.experience_version_id == experience_version_id,
                Verification.passed.is_(True),
            )
        )
    ).scalar_one_or_none()

    total = len(successful) + len(failed)
    stat = {
        "experience_version_id": experience_version_id,
        "experience_id": await _experience_id(db, experience_version_id),
        "successful_runs": len(successful),
        "failed_runs": len(failed),
        "median_duration_ms": _percentile(durations, 0.50),
        "p95_duration_ms": _percentile(durations, 0.95),
        "success_rate": (len(successful) / total) if total else 0.0,
        "confidence": wilson_lower_bound(len(successful), len(failed)),
        "distinct_organizations": len({row.organization_id for row in successful}),
        "failure_modes": failure_modes,
        "last_verified_at": last_verified,
        "updated_at": now(),
    }

    statement = insert(ExecutionStat).values(**stat)
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[ExecutionStat.experience_version_id],
            set_={k: v for k, v in stat.items() if k != "experience_version_id"},
        )
    )

    if successful:
        await _promote(db, str(stat["experience_id"]), last_verified)

    return (
        await db.execute(
            select(ExecutionStat).where(
                ExecutionStat.experience_version_id == experience_version_id
            )
        )
    ).scalar_one()


async def _experience_id(db: AsyncSession, experience_version_id: str) -> str:
    value = (
        await db.execute(
            select(Execution.experience_id)
            .where(Execution.experience_version_id == experience_version_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if value is not None:
        return str(value)
    from boobs_schemas.tables import ExperienceVersion

    return str(
        (
            await db.execute(
                select(ExperienceVersion.experience_id).where(
                    ExperienceVersion.id == experience_version_id
                )
            )
        ).scalar_one()
    )


async def _promote(db: AsyncSession, experience_id: str, last_verified: datetime | None) -> None:
    """First proven execution moves an Experience from candidate to verified.

    Deliberately the whole of promotion for now (spec section 22 describes a
    richer policy): one proven run is the difference between "someone claims
    this works" and "this has worked".
    """
    experience = (
        await db.execute(select(Experience).where(Experience.id == experience_id))
    ).scalar_one_or_none()
    if experience is None or experience.status == ExperienceStatus.QUARANTINED:
        return
    experience.status = ExperienceStatus.VERIFIED
    experience.verification_level = VerificationLevel.PROVEN
    experience.updated_at = last_verified or now()


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    index = min(len(values) - 1, int(round(fraction * (len(values) - 1))))
    return values[index]


def as_dict(stat: ExecutionStat) -> dict[str, Any]:
    return {
        "successful_runs": stat.successful_runs,
        "failed_runs": stat.failed_runs,
        "success_rate": stat.success_rate,
        "confidence": stat.confidence,
        "last_verified_at": stat.last_verified_at,
        "median_duration_ms": stat.median_duration_ms,
        "p95_duration_ms": stat.p95_duration_ms,
        "distinct_organizations": stat.distinct_organizations,
        "failure_modes": dict(stat.failure_modes or {}),
    }
