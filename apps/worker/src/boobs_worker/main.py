"""Execution worker (spec sections 9, 15, 18, 20).

Dequeue -> sandbox -> events -> verify -> evidence. This process is the only
one that talks to a container runtime, and it runs wherever Docker actually
is, which for the MVP is the developer's machine rather than Railway.
"""

from __future__ import annotations

import base64
from typing import Any

from arq.connections import RedisSettings
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound

from boobs_common import ids, storage
from boobs_common.clock import now
from boobs_common.config import settings
from boobs_domain.entities import VerificationSpec
from boobs_domain.enums import ExecutionStatus
from boobs_domain.events import EventType
from boobs_domain.protocols import SandboxRequest, SandboxResult
from boobs_execution import DockerOciRuntime
from boobs_observability import configure, logger
from boobs_reputation.evidence import recompute
from boobs_schemas.db import session
from boobs_schemas.tables import (
    Artifact,
    Execution,
    ExecutionEvent,
    ExperienceVersion,
    Verification,
)
from boobs_verification.verifiers import RegistryVerifier

QUEUE_NAME = "80085:executions"
log = logger(__name__)
runtime = DockerOciRuntime()
verifier = RegistryVerifier()


async def execute_experience(_: dict[str, Any], execution_id: str) -> str:
    """Run one execution end to end. Returns the terminal status."""
    try:
        async with session() as db:
            execution = (
                await db.execute(select(Execution).where(Execution.id == execution_id))
            ).scalar_one()
            version = (
                await db.execute(
                    select(ExperienceVersion).where(
                        ExperienceVersion.id == execution.experience_version_id
                    )
                )
            ).scalar_one()
            artifact = (
                await db.execute(select(Artifact).where(Artifact.id == version.artifact_id))
            ).scalar_one()
    except NoResultFound:
        # The row this job names does not exist -- a queue that outlived its
        # database. Retrying can never succeed and would starve the worker of
        # slots, so drop it and say so.
        log.warning("execution_row_missing", execution_id=execution_id, action="abandoned")
        return "abandoned"

    async with session() as db:
        execution = (
            await db.execute(select(Execution).where(Execution.id == execution_id))
        ).scalar_one()

        execution.status = ExecutionStatus.RUNNING
        execution.started_at = now()
        await _event(
            db,
            execution_id,
            EventType.EXECUTION_STARTED,
            {
                "image": artifact.reference,
                "digest": artifact.digest,
            },
        )
        await db.commit()

    inputs = await _load_inputs(execution_id)
    limits = settings().sandbox
    request = SandboxRequest(
        execution_id=execution_id,
        image=artifact.reference,
        command=list(version.command),
        input_files=inputs,
        cpu=limits.cpu,
        memory_mb=limits.memory_mb,
        tmpfs_mb=limits.tmpfs_mb,
        timeout_seconds=limits.timeout_seconds,
        pids=limits.pids,
        max_output_bytes=limits.max_output_bytes,
        network=version.requires_network,
    )

    try:
        result = await runtime.execute(request)
    except Exception as exc:  # noqa: BLE001 - a runtime failure is a failed run
        log.error("sandbox_error", execution_id=execution_id, error=str(exc))
        result = SandboxResult(
            status=ExecutionStatus.FAILED, exit_code=None, duration_ms=0, error=str(exc)
        )

    output_key = await _store_outputs(execution_id, result)
    logs_key = await _store_logs(execution_id, result)

    async with session() as db:
        execution = (
            await db.execute(select(Execution).where(Execution.id == execution_id))
        ).scalar_one()
        version = (
            await db.execute(
                select(ExperienceVersion).where(
                    ExperienceVersion.id == execution.experience_version_id
                )
            )
        ).scalar_one()

        await _event(
            db,
            execution_id,
            EventType.EXECUTION_COMPLETED,
            {
                "status": str(result.status),
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "outputs": sorted(result.output_files),
            },
        )

        # Verification happens here, not on the agent's word (spec section 18).
        declared = version.verification or {}
        if declared.get("verifier"):
            await _event(
                db,
                execution_id,
                EventType.VERIFICATION_STARTED,
                {
                    "verifier": declared["verifier"],
                },
            )
            outcome = await verifier.verify(
                result,
                VerificationSpec(verifier=declared["verifier"], config=declared.get("config", {})),
            )
            db.add(
                Verification(
                    id=ids.new_id(ids.VERIFICATION),
                    execution_id=execution_id,
                    experience_version_id=version.id,
                    verifier=declared["verifier"],
                    passed=outcome.passed,
                    level=outcome.level,
                    detail=outcome.detail,
                    created_at=now(),
                )
            )
            await _event(
                db,
                execution_id,
                EventType.VERIFICATION_COMPLETED,
                {
                    "passed": outcome.passed,
                    "level": str(outcome.level),
                },
            )

        execution.status = result.status
        execution.exit_code = result.exit_code
        execution.duration_ms = result.duration_ms
        execution.output_key = output_key
        execution.logs_key = logs_key
        execution.error = result.error
        execution.completed_at = now()
        await db.flush()

        await recompute(db, version.id)
        await db.commit()

    log.info("execution_finished", execution_id=execution_id, status=str(result.status))
    return str(result.status)


async def _event(db: Any, execution_id: str, event_type: str, payload: dict[str, Any]) -> None:
    from sqlalchemy import func

    sequence = (
        await db.execute(
            select(func.coalesce(func.max(ExecutionEvent.sequence), 0) + 1).where(
                ExecutionEvent.execution_id == execution_id
            )
        )
    ).scalar_one()
    db.add(
        ExecutionEvent(
            id=ids.new_id(ids.EVENT),
            execution_id=execution_id,
            sequence=int(sequence),
            event_type=str(event_type),
            payload=payload,
            created_at=now(),
        )
    )
    await db.flush()


async def _load_inputs(execution_id: str) -> dict[str, bytes]:
    try:
        stored = await storage.get_json(f"executions/{execution_id}/inputs.json")
    except Exception:  # noqa: BLE001 - no inputs is the common case
        return {}
    return {name: base64.b64decode(blob) for name, blob in stored.items()}


async def _store_outputs(execution_id: str, result: SandboxResult) -> str | None:
    if not result.output_files:
        return None
    return await storage.put_json(
        storage.output_key(execution_id),
        {name: base64.b64encode(blob).decode() for name, blob in result.output_files.items()},
    )


async def _store_logs(execution_id: str, result: SandboxResult) -> str:
    return await storage.put_json(
        storage.logs_key(execution_id),
        {
            "stdout": base64.b64encode(result.stdout).decode(),
            "stderr": base64.b64encode(result.stderr).decode(),
            "truncated": result.truncated,
        },
    )


async def startup(_: dict[str, Any]) -> None:
    configure("80085-worker")
    await storage.ensure_bucket()


class WorkerSettings:
    functions = [execute_experience]
    on_startup = startup
    queue_name = QUEUE_NAME
    max_jobs = 4
    job_timeout = 900
    # A sandbox run that failed transiently deserves a second chance; five
    # attempts of a job that cannot work just delays every other job.
    max_tries = 2
    redis_settings = RedisSettings.from_dsn(settings().redis_url)
