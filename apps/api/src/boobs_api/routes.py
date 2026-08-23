"""HTTP surface (spec section 32).

Six operations matter: DISCOVER, RECALL, EXECUTE, VERIFY, RECORD, REUSE.
Everything here is one of those, plus health and key bootstrap.
"""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Any

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select, text

from boobs_api import leases, limits
from boobs_api.deps import CurrentPrincipal, DbSession, MaybePrincipal
from boobs_api.repositories import (
    ArtifactRepository,
    ExecutionRepository,
    ExperienceRepository,
    SqlEventStore,
)
from boobs_common import ids, storage
from boobs_common.clock import now
from boobs_common.errors import Forbidden, NotFound, ValidationError
from boobs_domain.entities import Constraints, Environment, Evidence, VerificationSpec
from boobs_domain.enums import (
    ExecutionStatus,
    ExperienceStatus,
    VerificationLevel,
    Visibility,
)
from boobs_domain.protocols import Principal, RecallQuery, SandboxResult
from boobs_reputation.evidence import recompute
from boobs_schemas import db as database
from boobs_schemas.api import (
    BootstrapRequest,
    EventResponse,
    ExecuteRequest,
    ExecutionResponse,
    ExperienceResponse,
    GoalIn,
    RecallMatch,
    RecallRequest,
    RecallResponse,
    RecordExperienceRequest,
    VerificationResponse,
    VerifyRequest,
)
from boobs_schemas.tables import (
    Agent,
    ApiKey,
    Execution,
    ExecutionStat,
    Experience,
    ExperienceVersion,
    Organization,
    Verification,
)
from boobs_security.keys import Scope, generate
from boobs_security.policy import ScopePolicyEngine
from boobs_verification.verifiers import RegistryVerifier

router = APIRouter(prefix="/v1")
policy = ScopePolicyEngine()

TERMINAL = {
    ExecutionStatus.SUCCEEDED,
    ExecutionStatus.FAILED,
    ExecutionStatus.TIMEOUT,
    ExecutionStatus.REJECTED,
}


# --------------------------------------------------------------------- health


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(db: DbSession, response: Response) -> dict[str, Any]:
    checks = {
        "database": await _db_healthy(db),
        # Checked separately because it failed separately: a Postgres image
        # without pgvector answers SELECT 1 happily while every recall 500s.
        "pgvector": await _pgvector_healthy(db),
        "object_storage": await storage.healthy(),
    }
    ok = all(checks.values())
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    # Queue depth is reported, not checked: a backlog means no worker is
    # attached, which is an operational fact rather than an unhealthy API.
    return {"ready": ok, "checks": checks, "queued_executions": await leases.depth(db)}


async def _db_healthy(db: DbSession) -> bool:
    try:
        await db.execute(select(1))
        return True
    except Exception:  # noqa: BLE001 - readiness reports, never raises
        return False


async def _pgvector_healthy(db: DbSession) -> bool:
    """Prove the vector type actually works, not merely that it is registered.

    The extension can be present in the catalog while its shared library is
    missing from the image -- swapping a Postgres image for one without
    pgvector does exactly that. Casting a literal touches the library, so this
    fails when recall would fail instead of after someone reports it.
    """
    try:
        await db.rollback()
        await db.execute(text("SELECT '[1,0,0]'::vector"))
        return True
    except Exception:  # noqa: BLE001 - readiness reports, never raises
        await db.rollback()
        return False


# ------------------------------------------------------------------ bootstrap


@router.post("/bootstrap", status_code=status.HTTP_201_CREATED)
async def bootstrap(request: BootstrapRequest, db: DbSession) -> dict[str, Any]:
    """Create an organization, an agent and its first API key.

    Guarded by BOOBS_BOOTSTRAP_TOKEN because it mints credentials. This is
    the MVP's account creation; a real signup flow replaces it.

    `scopes` defaults to the ordinary agent scopes. Pass ["worker:execute"] to
    mint a worker key -- a worker should be able to lease and report, and
    nothing else.
    """
    import os

    expected = os.environ.get("BOOBS_BOOTSTRAP_TOKEN", "")
    if not expected or request.token != expected:
        raise Forbidden("invalid bootstrap token")

    granted = sorted(set(request.scopes)) if request.scopes else sorted(Scope.ALL)
    unknown = set(granted) - set(Scope.KNOWN)
    if unknown:
        raise ValidationError(f"unknown scopes: {sorted(unknown)}")

    org = Organization(id=ids.new_id(ids.ORGANIZATION), name=request.organization, created_at=now())
    agent_row = Agent(
        id=ids.new_id(ids.AGENT),
        organization_id=org.id,
        name=request.agent,
        created_at=now(),
    )
    plaintext, key_hash = generate()
    key = ApiKey(
        id=ids.new_id(ids.API_KEY),
        organization_id=org.id,
        agent_id=agent_row.id,
        name=f"{request.agent} default",
        key_hash=key_hash,
        scopes=granted,
        created_at=now(),
    )
    # Flushed in dependency order: without ORM relationships, the unit of work
    # does not sort these three inserts for us.
    for row in (org, agent_row, key):
        db.add(row)
        await db.flush()
    # The only time the plaintext key exists anywhere.
    return {
        "organization_id": org.id,
        "agent_id": agent_row.id,
        "api_key": plaintext,
        "scopes": granted,
    }


@router.post("/keys", status_code=status.HTTP_201_CREATED)
async def mint_key(
    http: Request, db: DbSession, label: str | None = Query(default=None)
) -> dict[str, Any]:
    """Mint a key with no signup, no email and no human in the loop.

    Every credential we demand costs us a contributor, and contributors are
    the product. So this asks for nothing: the key *is* the account.

    What we get in exchange is attribution, not identity -- a stable id that
    ties one actor's contributions together so they can be revoked as a set if
    they turn out to be garbage. Knowing who someone is was never the point.

    Recording is safe to open this wide because recording is not the same as
    being recommended: ranking weights a Wilson lower bound over *verified*
    runs, so an Experience nobody has successfully run is never returned as
    "use", however many of them a spammer records.
    """
    limits.MINT.check(limits.client_ip(http))

    name = (label or "anonymous").strip()[:200] or "anonymous"
    org = Organization(id=ids.new_id(ids.ORGANIZATION), name=f"self-serve:{name}", created_at=now())
    agent_row = Agent(
        id=ids.new_id(ids.AGENT), organization_id=org.id, name=name, created_at=now()
    )
    plaintext, key_hash = generate()
    # Read, write and run -- but never admin, and never the worker scope.
    granted = sorted({Scope.EXPERIENCES_READ, Scope.EXPERIENCES_WRITE, Scope.EXECUTIONS_RUN})
    key = ApiKey(
        id=ids.new_id(ids.API_KEY),
        organization_id=org.id,
        agent_id=agent_row.id,
        name=f"{name} self-serve",
        key_hash=key_hash,
        scopes=granted,
        created_at=now(),
    )
    for row in (org, agent_row, key):
        db.add(row)
        await db.flush()
    return {
        "api_key": plaintext,  # the only time the plaintext exists anywhere
        "organization_id": org.id,
        "agent_id": agent_row.id,
        "scopes": granted,
        "note": (
            "Store this now. It is not recoverable, and there is no "
            "account to recover it into."
        ),
    }


# ----------------------------------------------------------------- experience


@router.post("/experiences", status_code=status.HTTP_201_CREATED)
async def record_experience(
    request: RecordExperienceRequest, http: Request, db: DbSession, principal: CurrentPrincipal
) -> ExperienceResponse:
    """RECORD: an agent contributes a reusable capability."""
    limits.RECORD.check(limits.client_ip(http))
    repository = ExperienceRepository(db)
    experience, version = await repository.create(principal, request)
    artifact = await ArtifactRepository(db).resolve(version.artifact_id)
    return _experience_response(experience, version, artifact.digest, Evidence())


@router.get("/experiences/{experience_id}")
async def get_experience(
    experience_id: str,
    db: DbSession,
    principal: CurrentPrincipal,
    version: int | None = Query(default=None),
) -> ExperienceResponse:
    repository = ExperienceRepository(db)
    experience = await repository.get(principal, experience_id)
    version_row = await repository.get_version(principal, experience_id, version)
    artifact = await ArtifactRepository(db).resolve(version_row.artifact_id)
    return _experience_response(
        experience, version_row, artifact.digest, await _evidence(db, version_row.id)
    )


@router.post("/experiences/recall")
async def recall_experiences(
    request: RecallRequest, http: Request, db: DbSession, principal: MaybePrincipal
) -> RecallResponse:
    """RECALL: the question that has to be cheaper to ask than to reinvent.

    The only operation that needs no credential. An agent that discovers this
    API should be able to ask it something immediately -- a shared brain that
    demands a signup before it will answer is just a database with a landing
    page. Callers without a key see public Experiences only.
    """
    limits.RECALL.check(limits.client_ip(http))
    started = time.monotonic()
    query = RecallQuery(
        task=request.task,
        environment=Environment(
            os=request.context.os,
            architecture=request.context.architecture,
            runtime=request.context.runtime,
            runtime_version=request.context.runtime_version,
        ),
        constraints=Constraints(
            network=request.constraints.network,
            max_duration_seconds=request.constraints.max_duration_seconds,
            required_capabilities=tuple(request.constraints.required_capabilities),
        ),
        limit=request.limit,
    )
    candidates = await ExperienceRepository(db).search(principal, query)
    return RecallResponse(
        matches=[RecallMatch(**candidate.model_dump()) for candidate in candidates],
        query_id=ids.new_id("qry"),
        took_ms=int((time.monotonic() - started) * 1000),
    )


@router.get("/recall")
async def recall_via_url(
    http: Request,
    db: DbSession,
    principal: MaybePrincipal,
    q: str = Query(min_length=3, max_length=2000, description="The task, in your own words."),
    limit: int = Query(default=5, ge=1, le=20),
) -> Response:
    """The same question, askable with nothing but a URL.

    MCP is the good path, but it presumes a client and a config file. Plenty of
    agents have only a fetch tool, and a product that cannot be tried with one
    GET is a product most of them will never try. Returns markdown by default
    because that is what a language model reads best; JSON on request.
    """
    limits.RECALL.check(limits.client_ip(http))
    candidates = await ExperienceRepository(db).search(
        principal, RecallQuery(task=q, limit=limit)
    )
    matches = [RecallMatch(**candidate.model_dump()) for candidate in candidates]

    if "application/json" in http.headers.get("accept", ""):
        return JSONResponse(
            content={"query": q, "matches": [m.model_dump(mode="json") for m in matches]}
        )

    lines = [f"# recall: {q}", ""]
    if not matches:
        lines += [
            "No verified Experience matches that yet.",
            "",
            "An empty answer is a correct answer: relevance is not evidence, and we",
            "would rather tell you nothing than point you at something unproven.",
            "",
            "If you solve it yourself, record it and the next agent will find it.",
            "Get a key with: curl -X POST https://api.80085.ai/v1/keys",
        ]
    for m in matches:
        lines += [
            f"## {m.goal}",
            "",
            f"- recommendation: **{m.recommendation}**",
            f"- confidence: {m.confidence:.1%} (Wilson lower bound on verified runs)",
            f"- verified runs: {m.successful_runs}",
            f"- compatibility: {m.compatibility}",
            f"- experience_id: `{m.experience_id}` (version {m.version})",
            "",
            f"Run it: `run_experience(experience_id=\"{m.experience_id}\")`",
            "",
        ]
    return PlainTextResponse("\n".join(lines), media_type="text/markdown; charset=utf-8")


# ------------------------------------------------------------------ execution


@router.post("/experiences/{experience_id}/execute", status_code=status.HTTP_202_ACCEPTED)
async def execute_experience(
    experience_id: str,
    request: ExecuteRequest,
    http: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    response: Response,
) -> ExecutionResponse:
    """EXECUTE: run one exact, digest-pinned version. Never 'latest' bytes."""
    # The only operation that spends real compute, so it gets the tightest
    # limit of the four. The sandbox has no network and a 60s ceiling, which
    # makes it close to useless as stolen compute even before this.
    limits.EXECUTE.check(limits.client_ip(http))
    repository = ExperienceRepository(db)
    experience = await repository.get(principal, experience_id)
    await policy.authorize(principal, "execution.run", experience)
    version = await repository.get_version(principal, experience_id, request.version)
    artifact = await ArtifactRepository(db).resolve(version.artifact_id)

    execution = Execution(
        id=ids.new_id(ids.EXECUTION),
        organization_id=principal.organization_id,
        agent_id=principal.agent_id,
        experience_id=experience.id,
        experience_version_id=version.id,
        artifact_digest=artifact.digest,
        status=ExecutionStatus.QUEUED,
        created_at=now(),
    )
    await ExecutionRepository(db).create(execution)

    inputs = request.decoded_inputs()
    if inputs:
        await storage.put_json(
            f"executions/{execution.id}/inputs.json",
            {name: base64.b64encode(blob).decode() for name, blob in inputs.items()},
        )

    # Committing is the enqueue: the executions table is the queue, and a
    # worker claims rows from it with SELECT ... FOR UPDATE SKIP LOCKED.
    await db.commit()

    if request.wait_seconds:
        await _await_terminal(execution.id, request.wait_seconds)

    result = await _execution_response(execution.id, principal)
    if result.status in TERMINAL:
        response.status_code = status.HTTP_200_OK
    return result


@router.get("/executions/{execution_id}")
async def get_execution(
    execution_id: str, db: DbSession, principal: CurrentPrincipal
) -> ExecutionResponse:
    await ExecutionRepository(db).get(principal, execution_id)
    return await _execution_response(execution_id, principal)


@router.get("/executions/{execution_id}/events")
async def get_execution_events(
    execution_id: str, db: DbSession, principal: CurrentPrincipal
) -> list[EventResponse]:
    await ExecutionRepository(db).get(principal, execution_id)
    events = [
        EventResponse(
            sequence=event.sequence,
            event_type=event.event_type,
            payload=event.payload,
            created_at=event.created_at,
        )
        async for event in SqlEventStore(db).stream(execution_id)
    ]
    return events


@router.post("/executions/{execution_id}/verify")
async def verify_execution(
    execution_id: str,
    request: VerifyRequest,
    db: DbSession,
    principal: CurrentPrincipal,
) -> VerificationResponse:
    """VERIFY: turn a completed execution into evidence, or refuse to."""
    execution = await ExecutionRepository(db).get(principal, execution_id)
    await policy.authorize(principal, "execution.verify", execution)
    if execution.status not in TERMINAL:
        raise ValidationError(f"execution {execution_id} has not finished ({execution.status})")

    version = (
        await db.execute(
            select(ExperienceVersion).where(ExperienceVersion.id == execution.experience_version_id)
        )
    ).scalar_one()

    declared = version.verification or {}
    verifier_name = request.verifier or declared.get("verifier")
    if not verifier_name:
        raise ValidationError("no verifier declared on this version and none supplied")
    config = request.config if request.config is not None else declared.get("config", {})

    result = await _reconstruct_result(execution)
    outcome = await RegistryVerifier().verify(
        result, VerificationSpec(verifier=verifier_name, config=config)
    )

    record = Verification(
        id=ids.new_id(ids.VERIFICATION),
        execution_id=execution.id,
        experience_version_id=version.id,
        verifier=verifier_name,
        passed=outcome.passed,
        level=outcome.level,
        detail=outcome.detail,
        created_at=now(),
    )
    db.add(record)
    await db.flush()
    await recompute(db, version.id)
    return VerificationResponse(
        verification_id=record.id,
        verifier=verifier_name,
        passed=record.passed,
        level=VerificationLevel(record.level),
        detail=record.detail,
        created_at=record.created_at,
    )


# --------------------------------------------------------------------- shared


def _experience_response(
    experience: Experience,
    version: ExperienceVersion,
    digest: str,
    evidence: Evidence,
) -> ExperienceResponse:
    return ExperienceResponse(
        experience_id=experience.id,
        version=version.version,
        experience_version_id=version.id,
        goal=GoalIn(
            statement=experience.goal_statement,
            intent=experience.goal_intent,
            tags=list(experience.tags or ()),
        ),
        status=ExperienceStatus(experience.status),
        verification_level=VerificationLevel(experience.verification_level),
        visibility=Visibility(experience.visibility),
        artifact_digest=digest,
        evidence=evidence,
        created_at=experience.created_at,
    )


async def _evidence(db: DbSession, experience_version_id: str) -> Evidence:
    stat = (
        await db.execute(
            select(ExecutionStat).where(
                ExecutionStat.experience_version_id == experience_version_id
            )
        )
    ).scalar_one_or_none()
    if stat is None:
        return Evidence()
    return Evidence(
        successful_runs=stat.successful_runs,
        failed_runs=stat.failed_runs,
        success_rate=stat.success_rate,
        confidence=stat.confidence,
        last_verified_at=stat.last_verified_at,
        median_duration_ms=stat.median_duration_ms,
        p95_duration_ms=stat.p95_duration_ms,
        distinct_organizations=stat.distinct_organizations,
        failure_modes=dict(stat.failure_modes or {}),
    )


async def _await_terminal(execution_id: str, seconds: int) -> None:
    """Block until the worker finishes, in its own sessions so it sees commits."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        async with database.session() as db:
            state = (
                await db.execute(select(Execution.status).where(Execution.id == execution_id))
            ).scalar_one_or_none()
        if state in TERMINAL:
            return
        await asyncio.sleep(0.2)


async def _reconstruct_result(execution: Execution) -> SandboxResult:
    """Rebuild the sandbox result from stored artefacts so verification can be
    re-run later, by a different verifier, without re-executing."""
    outputs: dict[str, bytes] = {}
    stdout = stderr = b""
    if execution.output_key:
        stored = await storage.get_json(execution.output_key)
        outputs = {name: base64.b64decode(blob) for name, blob in stored.items()}
    if execution.logs_key:
        logs = await storage.get_json(execution.logs_key)
        stdout = base64.b64decode(logs.get("stdout", ""))
        stderr = base64.b64decode(logs.get("stderr", ""))
    return SandboxResult(
        status=ExecutionStatus(execution.status),
        exit_code=execution.exit_code,
        duration_ms=execution.duration_ms or 0,
        stdout=stdout,
        stderr=stderr,
        output_files=outputs,
    )


async def _execution_response(execution_id: str, principal: Principal) -> ExecutionResponse:
    async with database.session() as db:
        execution = (
            await db.execute(select(Execution).where(Execution.id == execution_id))
        ).scalar_one_or_none()
        if execution is None or execution.organization_id != principal.organization_id:
            raise NotFound(f"execution {execution_id} not found")
        version = (
            await db.execute(
                select(ExperienceVersion).where(
                    ExperienceVersion.id == execution.experience_version_id
                )
            )
        ).scalar_one()
        verification = (
            await db.execute(
                select(Verification)
                .where(Verification.execution_id == execution.id)
                .order_by(Verification.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    result = await _reconstruct_result(execution) if execution.output_key else None
    return ExecutionResponse(
        execution_id=execution.id,
        experience_id=execution.experience_id,
        version=version.version,
        artifact_digest=execution.artifact_digest,
        status=ExecutionStatus(execution.status),
        exit_code=execution.exit_code,
        duration_ms=execution.duration_ms,
        outputs=(
            {name: base64.b64encode(blob).decode() for name, blob in result.output_files.items()}
            if result
            else {}
        ),
        stdout=result.stdout.decode(errors="replace") if result else None,
        stderr=result.stderr.decode(errors="replace") if result else None,
        error=execution.error,
        verification=(
            VerificationResponse(
                verification_id=verification.id,
                verifier=verification.verifier,
                passed=verification.passed,
                level=VerificationLevel(verification.level),
                detail=verification.detail,
                created_at=verification.created_at,
            )
            if verification
            else None
        ),
        created_at=execution.created_at,
    )
