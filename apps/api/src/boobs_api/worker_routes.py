"""The worker protocol.

Execution happens off-platform, because a sandbox needs a container runtime
that a managed platform will not give a service. So a worker is an HTTPS
client: it leases work, runs it, and reports what happened.

Two properties this buys, both of which matter more than the convenience:

  * A worker holds one scoped API key. It never gets database or queue
    credentials, and no datastore has to be exposed to the internet.
  * **Verification runs here, not in the worker.** The worker reports the raw
    result -- exit code, stdout, output bytes -- and the API decides whether
    that constitutes success. A worker cannot vote on its own evidence.
"""

from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from boobs_api import leases
from boobs_api.deps import CurrentPrincipal, DbSession, release
from boobs_api.repositories import SqlEventStore
from boobs_common import ids, storage
from boobs_common.clock import now
from boobs_common.errors import Forbidden, NotFound, ValidationError
from boobs_domain.entities import VerificationSpec
from boobs_domain.enums import ExecutionStatus, VerificationLevel
from boobs_domain.events import EventType
from boobs_domain.protocols import SandboxResult
from boobs_observability import counter
from boobs_reputation.evidence import recompute
from boobs_schemas.tables import (
    Artifact,
    Execution,
    Experience,
    ExperienceVersion,
    Verification,
)
from boobs_security.keys import Scope
from boobs_verification.verifiers import RegistryVerifier

router = APIRouter(prefix="/v1/worker", tags=["worker"])
verifier = RegistryVerifier()

# The one place every run ends, so the one place worth counting them. Spec
# section 33's execution_success_rate, verification_success_rate,
# successful_reuse_rate and cross_agent_reuse_rate are all slices of this.
_executions = counter("executions_completed", "runs reported by a worker, once each")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LeaseRequest(Strict):
    worker_id: str = Field(min_length=3, max_length=64)
    lease_seconds: int = Field(default=leases.DEFAULT_LEASE_SECONDS, ge=30, le=3600)


class LeasedJob(Strict):
    execution_id: str
    experience_id: str
    experience_version_id: str
    image: str
    command: list[str]
    inputs: dict[str, str] = Field(default_factory=dict, description="filename -> base64")
    network: bool = False
    lease_expires_at: Any = None


class LeaseResponse(Strict):
    job: LeasedJob | None = None
    queue_depth: int = 0


class ResultRequest(Strict):
    worker_id: str = Field(min_length=3, max_length=64)
    status: ExecutionStatus
    exit_code: int | None = None
    duration_ms: int = Field(ge=0)
    stdout: str = Field(default="", description="base64")
    stderr: str = Field(default="", description="base64")
    outputs: dict[str, str] = Field(default_factory=dict, description="filename -> base64")
    truncated: bool = False
    error: str | None = None


class ResultResponse(Strict):
    execution_id: str
    status: ExecutionStatus
    verified: bool | None = None
    verifier: str | None = None


def _require_worker(principal: CurrentPrincipal) -> None:
    if Scope.WORKER not in principal.scopes and Scope.ADMIN not in principal.scopes:
        raise Forbidden(f"missing scope {Scope.WORKER!r}")


@router.post("/lease")
async def lease(request: LeaseRequest, db: DbSession, principal: CurrentPrincipal) -> LeaseResponse:
    """Claim the next queued execution, if there is one.

    Returns `job: null` rather than an error when the queue is empty -- an idle
    worker is the normal case, not a failure.
    """
    _require_worker(principal)

    execution = await leases.claim_next(db, request.worker_id, request.lease_seconds)
    if execution is None:
        return LeaseResponse(job=None, queue_depth=0)

    version = (
        await db.execute(
            select(ExperienceVersion).where(ExperienceVersion.id == execution.experience_version_id)
        )
    ).scalar_one()
    artifact = (
        await db.execute(select(Artifact).where(Artifact.id == version.artifact_id))
    ).scalar_one()

    await SqlEventStore(db).append(
        execution.id,
        EventType.EXECUTION_STARTED,
        {"image": artifact.reference, "digest": artifact.digest, "worker": request.worker_id},
    )
    queue_depth = await leases.depth(db)

    # The claim commits before the inputs are fetched. claim_next holds a row
    # lock, so reading object storage first would hold both that lock and a
    # pooled connection for the length of an S3 round trip -- with every other
    # worker polling the same queue behind it.
    await release(db)

    inputs: dict[str, str] = {}
    try:
        inputs = await storage.get_json(f"executions/{execution.id}/inputs.json")
    except Exception:  # noqa: BLE001 - most executions have no inputs
        inputs = {}

    return LeaseResponse(
        job=LeasedJob(
            execution_id=execution.id,
            experience_id=execution.experience_id,
            experience_version_id=version.id,
            image=artifact.reference,
            command=list(version.command or []),
            inputs=inputs,
            network=version.requires_network,
            lease_expires_at=execution.lease_expires_at,
        ),
        queue_depth=queue_depth,
    )


@router.post("/executions/{execution_id}/result", status_code=status.HTTP_200_OK)
async def report_result(
    execution_id: str, request: ResultRequest, db: DbSession, principal: CurrentPrincipal
) -> ResultResponse:
    """Record what a worker observed, then decide independently whether it worked."""
    _require_worker(principal)

    execution = (
        await db.execute(select(Execution).where(Execution.id == execution_id))
    ).scalar_one_or_none()
    if execution is None:
        raise NotFound(f"execution {execution_id} not found")
    if execution.status != ExecutionStatus.RUNNING:
        raise ValidationError(
            f"execution {execution_id} is {execution.status}, not running; "
            "its lease may have expired and been reclaimed"
        )
    if execution.leased_by and execution.leased_by != request.worker_id:
        raise Forbidden(
            f"execution {execution_id} is leased by {execution.leased_by}, not {request.worker_id}"
        )

    version = (
        await db.execute(
            select(ExperienceVersion).where(ExperienceVersion.id == execution.experience_version_id)
        )
    ).scalar_one()

    outputs = {name: base64.b64decode(blob) for name, blob in request.outputs.items()}
    result = SandboxResult(
        status=request.status,
        exit_code=request.exit_code,
        duration_ms=request.duration_ms,
        stdout=base64.b64decode(request.stdout) if request.stdout else b"",
        stderr=base64.b64decode(request.stderr) if request.stderr else b"",
        output_files=outputs,
        truncated=request.truncated,
        error=request.error,
    )

    # The authorization checks above are the last thing that needs the database
    # until the record is written. Everything between here and the next write
    # is off-box I/O, so it runs with no transaction open and no connection held.
    await release(db)

    # Object storage is written before the row, never after. If the row landed
    # first and the upload then failed, output_key would point at bytes that do
    # not exist and every later read of this execution would fail. This way a
    # failure after the upload leaves an unreferenced object in the bucket,
    # which nothing reads and a lifecycle rule can sweep.
    output_key = None
    if outputs:
        output_key = await storage.put_json(storage.output_key(execution_id), request.outputs)
    logs_key = await storage.put_json(
        storage.logs_key(execution_id),
        {"stdout": request.stdout, "stderr": request.stderr, "truncated": request.truncated},
    )

    # Verifying is the platform's judgement, not the worker's, and it is pure
    # computation over the result -- so it happens here rather than holding a
    # connection. It is the seam an http or test_suite verifier would extend.
    verifier_name: str | None = None
    outcome = None
    declared = version.verification or {}
    if declared.get("verifier"):
        verifier_name = str(declared["verifier"])
        outcome = await verifier.verify(
            result,
            VerificationSpec(verifier=verifier_name, config=declared.get("config", {})),
        )

    # One transaction for the whole record: the events, the verdict and the
    # terminal row commit together or not at all.
    events = SqlEventStore(db)
    await events.append(
        execution_id,
        EventType.EXECUTION_COMPLETED,
        {
            "status": str(request.status),
            "exit_code": request.exit_code,
            "duration_ms": request.duration_ms,
            "outputs": sorted(outputs),
            "worker": request.worker_id,
        },
    )

    verified: bool | None = None
    if verifier_name and outcome is not None:
        await events.append(
            execution_id, EventType.VERIFICATION_STARTED, {"verifier": verifier_name}
        )
        db.add(
            Verification(
                id=ids.new_id(ids.VERIFICATION),
                execution_id=execution_id,
                experience_version_id=version.id,
                verifier=verifier_name,
                passed=outcome.passed,
                level=outcome.level,
                detail=outcome.detail,
                created_at=now(),
            )
        )
        await events.append(
            execution_id,
            EventType.VERIFICATION_COMPLETED,
            {"passed": outcome.passed, "level": str(VerificationLevel(outcome.level))},
        )
        verified = outcome.passed

    execution.status = request.status
    execution.exit_code = request.exit_code
    execution.duration_ms = request.duration_ms
    execution.output_key = output_key
    execution.logs_key = logs_key
    execution.error = request.error
    execution.completed_at = now()
    execution.lease_expires_at = None
    await db.flush()

    await recompute(db, version.id)

    # Reuse is only *cross-agent* when the organization running the Experience
    # is not the one that recorded it. That is the number the thesis rests on,
    # so it is measured from the row rather than inferred from traffic.
    owner = (
        await db.execute(
            select(Experience.organization_id).where(Experience.id == execution.experience_id)
        )
    ).scalar_one_or_none()
    _executions.add(
        1,
        {
            "status": str(request.status),
            # None means the version declared no verifier, which is neither a
            # pass nor a fail and must not be counted as either.
            "verified": "none" if verified is None else str(verified).lower(),
            "cross_organization": owner is not None and owner != execution.organization_id,
        },
    )

    return ResultResponse(
        execution_id=execution_id,
        status=request.status,
        verified=verified,
        verifier=verifier_name,
    )
