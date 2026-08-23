"""HTTP surface (spec section 32).

Six operations matter: DISCOVER, RECALL, EXECUTE, VERIFY, RECORD, REUSE.
Everything here is one of those, plus health and key bootstrap.
"""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from boobs_api import leases, limits, misses
from boobs_api.deps import ANONYMOUS, CurrentPrincipal, DbSession, MaybePrincipal, release
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
from boobs_retrieval.embedding import active_embedder
from boobs_retrieval.pipeline import RecallOutcome
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
from boobs_security import untrusted
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
    # The two probes that are not the database run first, before anything has
    # opened a transaction. A readiness check that pins a Postgres connection
    # while it waits on S3 -- or on a model load -- is itself a way to exhaust
    # the pool, and this endpoint has to keep answering precisely when the
    # dependencies are slow.
    object_storage = await storage.healthy()
    # A string, not a boolean, and deliberately so: running on the
    # non-semantic hashing fallback degrades recall without making the API
    # unready. Reported because the fallback is otherwise invisible from
    # outside the process. See DECISIONS.md 22.
    embedder_state = await asyncio.to_thread(active_embedder)
    checks = {
        "database": await _db_healthy(db),
        # Checked separately because it failed separately: a Postgres image
        # without pgvector answers SELECT 1 happily while every recall 500s.
        "pgvector": await _pgvector_healthy(db),
        "object_storage": object_storage,
        "embedder": embedder_state,
    }
    # "unavailable" means an embedder was demanded and will not load, so recall
    # would 500 -- genuinely unready. The hashing fallback is not.
    ok = all(checks.values()) and checks["embedder"] != "unavailable"
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
    # Committed here, not by get_db's teardown, which runs after the response
    # has gone out. See mint_key: handing back a credential that is not yet
    # committed is a 401 waiting to happen on the caller's next request.
    await release(db)
    # The only time the plaintext key exists anywhere.
    return {
        "organization_id": org.id,
        "agent_id": agent_row.id,
        "api_key": plaintext,
        "key_id": key.id,
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

    Nor can the holder of this key run its own Experience into a
    recommendation. Successes are capped per organization before they reach
    Wilson, and "use" needs runs from EVIDENCE_MIN_PROMOTION_ORGANIZATIONS
    distinct organizations. Keys being free is exactly why that had to stop
    being self-attestable -- see DECISIONS.md 41.
    """
    await limits.MINT.check(db, limits.client_ip(http))

    name = (label or "anonymous").strip()[:200] or "anonymous"
    org = Organization(id=ids.new_id(ids.ORGANIZATION), name=f"self-serve:{name}", created_at=now())
    agent_row = Agent(id=ids.new_id(ids.AGENT), organization_id=org.id, name=name, created_at=now())
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
    # The commit has to happen here, inside the handler. get_db commits in its
    # teardown, which FastAPI runs *after* the response has been sent -- so
    # this endpoint used to hand out a key whose row was not yet visible to
    # any other connection, and a caller who used it immediately got
    # `401 unknown api key`. Non-deterministically, on the one path that has
    # no signup to fall back on: the key is the account.
    #
    # All three rows are still written in one transaction, so a failure leaves
    # no half-made account; what changes is only that the transaction ends
    # before the credential leaves the process.
    await release(db)
    return {
        "api_key": plaintext,  # the only time the plaintext exists anywhere
        "organization_id": org.id,
        "agent_id": agent_row.id,
        # Returned so this key can be revoked later. There is no account to
        # log into and no way to look it up afterwards, so if it is not handed
        # over here it does not exist for the caller.
        "key_id": key.id,
        "scopes": granted,
        "note": (
            "Store this now. It is not recoverable, and there is no account to recover it into."
        ),
    }


@router.post("/keys/{key_id}/revoke")
async def revoke_key(key_id: str, db: DbSession, principal: CurrentPrincipal) -> dict[str, Any]:
    """Revoke a key, so that `docs/security.md` saying "revocable" is true.

    `revoked_at` has always been checked at authentication and never set by
    anything, which made revocation an UPDATE run by hand against production.

    Who may revoke what:

    * any key in an organization may revoke that organization's keys. Keys
      mint anonymously and there is no account to log into, so the
      organization is the only owner there is -- and it is exactly the set a
      contributor needs to be able to burn if their key leaks.
    * `admin` reaches across organizations, which is what ACTION_SCOPES's
      `admin.keys` names. Nothing else does.

    A caller therefore cannot revoke a stranger's key, which is the failure
    that would matter: revocation is a denial-of-service primitive pointed at
    whoever's id you can name, and key ids are handed out at mint.

    Idempotent -- revoking twice keeps the first timestamp, because the fact
    being recorded is when the key stopped working.
    """
    record = (await db.execute(select(ApiKey).where(ApiKey.id == key_id))).scalar_one_or_none()
    if record is None:
        raise NotFound(f"api key {key_id} not found")
    if record.organization_id != principal.organization_id:
        # Deliberately no resource argument: admin.keys is a MUTATING_ACTION,
        # and passing the row would make the policy engine demand ownership --
        # which is the one thing a cross-tenant admin revocation cannot have.
        await policy.authorize(principal, "admin.keys")
    if record.revoked_at is None:
        record.revoked_at = now()
    # Committed before the answer goes out, for the same reason minting is: a
    # caller told a key is revoked must not be able to use it a millisecond
    # later.
    await release(db)
    return {
        "key_id": record.id,
        "organization_id": record.organization_id,
        "revoked_at": record.revoked_at,
    }


# ----------------------------------------------------------------- experience


@router.post("/experiences", status_code=status.HTTP_201_CREATED)
async def record_experience(
    request: RecordExperienceRequest, http: Request, db: DbSession, principal: CurrentPrincipal
) -> ExperienceResponse:
    """RECORD: an agent contributes a reusable capability."""
    await limits.RECORD.check(db, limits.client_ip(http))
    repository = ExperienceRepository(db)
    experience, version = await repository.create(principal, request)
    artifact = await ArtifactRepository(db).resolve(version.artifact_id)
    response = _experience_response(experience, version, artifact.digest, Evidence())
    # Committed before the id goes out, for the same reason a credential is.
    # An agent that records something is told an experience_id and uses it on
    # the very next request -- to execute it, to recall it, to check what
    # another tenant can see. Returning the id from a transaction that commits
    # in dependency teardown, after the response has been written, means that
    # next request can arrive first and be answered 404.
    await release(db)
    return response


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


def _matches(outcome: RecallOutcome) -> list[RecallMatch]:
    """Recalled free text, returned as data.

    `goal` is written by whoever recorded the Experience, and a key mints with
    no identity check -- so it is a stranger's bytes on their way into another
    agent's context window. Neutralised here, at the point of return, so both
    representations get the same treatment and neither can grow a second
    opinion about it. Ordinary prose is unchanged.
    """
    out: list[RecallMatch] = []
    for candidate in outcome.matches:
        data = candidate.model_dump()
        data["goal"] = untrusted.neutralize(data["goal"])
        out.append(RecallMatch(**data))
    return out


def _remember_miss(
    background: BackgroundTasks,
    outcome: RecallOutcome,
    task: str,
    principal: Principal,
    query: RecallQuery,
) -> None:
    """Queue the miss row, if this was a miss.

    After the response, never during it: this is the demand signal, not the
    product, and a recall that fails because its telemetry failed would be the
    worst trade in the codebase.
    """
    if outcome.matches:
        return
    background.add_task(
        misses.record,
        task=task,
        parsed=outcome.parsed,
        environment=query.environment.model_dump(mode="json"),
        constraints=query.constraints.model_dump(mode="json"),
        candidates=outcome.considered,
        cleared=outcome.cleared,
        best_score=outcome.best_score,
        # Recall is keyless, so most misses are anonymous. That is fine and
        # deliberately not required -- but the anonymous principal names an
        # organization that does not exist, and storing that id would be a
        # lie dressed as attribution.
        organization_id=(
            None
            if principal.organization_id == ANONYMOUS.organization_id
            else principal.organization_id
        ),
    )


@router.post("/experiences/recall")
async def recall_experiences(
    request: RecallRequest,
    http: Request,
    db: DbSession,
    principal: MaybePrincipal,
    background: BackgroundTasks,
) -> RecallResponse:
    """RECALL: the question that has to be cheaper to ask than to reinvent.

    The only operation that needs no credential. An agent that discovers this
    API should be able to ask it something immediately -- a shared brain that
    demands a signup before it will answer is just a database with a landing
    page. Callers without a key see public Experiences only.
    """
    await limits.RECALL.check(db, limits.client_ip(http))
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
    outcome = await ExperienceRepository(db).search(principal, query)
    _remember_miss(background, outcome, request.task, principal, query)
    return RecallResponse(
        matches=_matches(outcome),
        query_id=ids.new_id("qry"),
        took_ms=int((time.monotonic() - started) * 1000),
    )


@router.get("/recall")
async def recall_via_url(
    http: Request,
    db: DbSession,
    principal: MaybePrincipal,
    background: BackgroundTasks,
    q: str = Query(min_length=3, max_length=2000, description="The task, in your own words."),
    limit: int = Query(default=5, ge=1, le=20),
) -> Response:
    """The same question, askable with nothing but a URL.

    MCP is the good path, but it presumes a client and a config file. Plenty of
    agents have only a fetch tool, and a product that cannot be tried with one
    GET is a product most of them will never try. Returns markdown by default
    because that is what a language model reads best; JSON on request.

    Which is precisely what makes this the sharp end of the prompt-injection
    problem: the document below is built to be read by a model, and the text in
    it came from strangers. So the document's *structure* is ours -- every
    heading, label and instruction on this page is written here, in source --
    and recalled text appears only inside a delimited untrusted block. See
    `boobs_security.untrusted` and docs/security.md.
    """
    await limits.RECALL.check(db, limits.client_ip(http))
    query = RecallQuery(task=q, limit=limit)
    outcome = await ExperienceRepository(db).search(principal, query)
    _remember_miss(background, outcome, q, principal, query)
    matches = _matches(outcome)

    if "application/json" in http.headers.get("accept", ""):
        return JSONResponse(
            content={"query": q, "matches": [m.model_dump(mode="json") for m in matches]}
        )

    lines = ["# recall", "", untrusted.NOTICE, "", untrusted.fenced(q, "query"), ""]
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
    for position, m in enumerate(matches, start=1):
        lines += [
            # The heading used to be the goal statement, which handed an
            # attacker the document outline. It is a number now.
            f"## match {position}: `{m.experience_id}` (version {m.version})",
            "",
            untrusted.fenced(m.goal, "goal"),
            "",
            f"- recommendation: **{m.recommendation}**",
            f"- confidence: {m.confidence:.1%} (Wilson lower bound on verified runs)",
            f"- verified runs: {m.successful_runs}",
            f"- compatibility: {m.compatibility}",
            "",
            f'Run it: `run_experience(experience_id="{m.experience_id}")`',
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
    await limits.EXECUTE.check(db, limits.client_ip(http))
    repository = ExperienceRepository(db)
    experience = await repository.get(principal, experience_id)
    await policy.authorize(principal, "execution.run", experience)
    version = await repository.get_version(principal, experience_id, request.version)
    artifact = await ArtifactRepository(db).resolve(version.artifact_id)

    executions = ExecutionRepository(db)
    key = request.idempotency_key
    existing = await executions.by_idempotency_key(principal, key) if key else None
    execution_id = existing.id if existing else ids.new_id(ids.EXECUTION)
    inputs = request.decoded_inputs()

    # Nothing below this point may run inside the request's transaction: an S3
    # round trip with a Postgres connection checked out is how twenty
    # connections disappear under a burst that never troubled the CPU.
    await release(db)

    if existing is None:
        # Inputs are staged before the row exists, because committing the row
        # IS the enqueue -- a worker can lease it the instant it lands. A row
        # whose inputs were never written would be run against nothing and the
        # result recorded as evidence, which is the one failure that corrupts
        # the product. The reverse order only ever leaks an object nothing
        # references, which a bucket lifecycle rule sweeps.
        if inputs:
            await storage.put_json(
                f"executions/{execution_id}/inputs.json",
                {name: base64.b64encode(blob).decode() for name, blob in inputs.items()},
            )
        execution_id = await _enqueue(
            db,
            executions,
            principal,
            Execution(
                id=execution_id,
                organization_id=principal.organization_id,
                agent_id=principal.agent_id,
                experience_id=experience.id,
                experience_version_id=version.id,
                artifact_digest=artifact.digest,
                status=ExecutionStatus.QUEUED,
                idempotency_key=key,
                created_at=now(),
            ),
        )

    if request.wait_seconds:
        await _await_terminal(execution_id, request.wait_seconds)

    result = await _execution_response(execution_id, principal)
    if result.status in TERMINAL:
        response.status_code = status.HTTP_200_OK
    return result


@router.get("/executions/{execution_id}")
async def get_execution(
    execution_id: str, db: DbSession, principal: CurrentPrincipal
) -> ExecutionResponse:
    await ExecutionRepository(db).get(principal, execution_id)
    # The tenancy check is the only thing this session was for. Releasing it
    # matters because _execution_response reads object storage and opens a
    # session of its own -- holding both at once doubles the pool per request.
    await release(db)
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
    http: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> VerificationResponse:
    """VERIFY: turn a completed execution into evidence, or refuse to."""
    # This was the one write path with no limit at all, which is the wrong one
    # to leave open: it is the endpoint that mints evidence, and evidence is
    # what the whole registry sells. Re-running a verifier is also arbitrary
    # work over stored artefacts, so it costs real CPU as well as credibility.
    await limits.VERIFY.check(db, limits.client_ip(http))
    execution = await ExecutionRepository(db).get(principal, execution_id)
    await policy.authorize(principal, "execution.verify", execution)
    if execution.status not in TERMINAL:
        raise ValidationError(f"execution {execution_id} has not finished ({execution.status})")

    version = (
        await db.execute(
            select(ExperienceVersion).where(ExperienceVersion.id == execution.experience_version_id)
        )
    ).scalar_one()

    # The version's declared verifier, and only that. See VerifyRequest.
    declared = version.verification or {}
    verifier_name = declared.get("verifier")
    if not verifier_name:
        raise ValidationError("this version declares no verifier; record a new version to add one")
    config = declared.get("config", {})

    # Rebuilding the result reads object storage, and re-running a verifier is
    # arbitrary work -- neither belongs on an open connection.
    await release(db)
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


async def _enqueue(
    db: DbSession,
    executions: ExecutionRepository,
    principal: Principal,
    execution: Execution,
) -> str:
    """Insert the queued row and commit. Committing is the enqueue: the
    executions table is the queue, and a worker claims rows from it with
    SELECT ... FOR UPDATE SKIP LOCKED.

    Returns the id of the execution that actually exists. A unique violation
    means a retry carrying the same idempotency key raced this one -- the
    partial unique index decides which insert wins, and the loser reports the
    winner's execution rather than spending a second sandbox run.
    """
    try:
        await executions.create(execution)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        winner = (
            await executions.by_idempotency_key(principal, execution.idempotency_key)
            if execution.idempotency_key
            else None
        )
        if winner is None:
            raise
        return winner.id
    return execution.id


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
