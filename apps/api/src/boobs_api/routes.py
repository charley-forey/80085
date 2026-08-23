"""HTTP surface (spec section 32).

Six operations matter: DISCOVER, RECALL, EXECUTE, VERIFY, RECORD, REUSE.
Everything here is one of those, plus health and key bootstrap.
"""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Any, Final

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from boobs_api import leases, limits, misses, scheduler
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
from boobs_reputation.evidence import quarantine, recompute
from boobs_retrieval.embedding import active_embedder
from boobs_retrieval.pipeline import RecallOutcome, visibility_clause
from boobs_schemas import db as database
from boobs_schemas.api import (
    BootstrapRequest,
    EventResponse,
    ExecuteRequest,
    ExecutionResponse,
    ExecutionTiersResponse,
    ExperienceResponse,
    GoalIn,
    GrantExecutionTiersRequest,
    LineageIn,
    LineageNode,
    LineageResponse,
    QuarantineRequest,
    QuarantineResponse,
    RecallMatch,
    RecallMissesResponse,
    RecallMissOut,
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
    JobRun,
    Organization,
    Policy,
    RecallMiss,
    Verification,
)
from boobs_security import untrusted
from boobs_security.keys import Scope, generate
from boobs_security.policy import TIER_GRANT_POLICY, ScopePolicyEngine, granted_tiers
from boobs_verification.verifiers import RegistryVerifier

router = APIRouter(prefix="/v1")
policy = ScopePolicyEngine()

TERMINAL = {
    ExecutionStatus.SUCCEEDED,
    ExecutionStatus.FAILED,
    ExecutionStatus.TIMEOUT,
    ExecutionStatus.REJECTED,
}

# The lineage relations, read off the request model so the read path cannot
# drift from the write path -- a seventh relation added to `LineageIn` is
# traversable the same day. Fixed order because JSONB guarantees none, and two
# identical traversals must not disagree about which edge came first.
LINEAGE_RELATIONS: Final[tuple[str, ...]] = tuple(LineageIn.model_fields)

# Six relations per node means depth 5 is 7776 nodes in the worst case, so the
# node budget -- not the depth -- is what actually bounds the answer. Depth
# bounds the number of round trips: one pair of queries per level.
MAX_LINEAGE_NODES: Final = 200


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
    #
    # Scheduled jobs likewise. A cron service that stopped firing is not an
    # unhealthy API -- recall and execution carry on working -- but it means
    # evidence has quietly stopped being reconciled, and until now the only
    # trace was a log line in a Railway service nobody opens. Reported as an
    # age so a reader needs no clock of their own; null means it has never run
    # here, which is what a cron service that was never created looks like.
    return {
        "ready": ok,
        "checks": checks,
        "queued_executions": await leases.depth(db),
        "jobs": await _job_ages(db),
    }


async def _job_ages(db: DbSession) -> dict[str, dict[str, Any]]:
    """Seconds since each scheduled job last finished, by name.

    Every job the scheduler knows about appears, whether or not it has ever
    run: a name that is simply absent from the response is indistinguishable
    from a name nobody thought to look for, and "never" is the answer worth
    seeing.
    """
    rows = {row.name: row for row in (await db.execute(select(JobRun))).scalars()}
    moment = now()
    ages: dict[str, dict[str, Any]] = {}
    for name in sorted(scheduler.JOBS):
        row = rows.get(name)
        if row is None:
            ages[name] = {"finished_at": None, "age_seconds": None, "affected": None}
            continue
        ages[name] = {
            "finished_at": row.finished_at.isoformat(),
            "age_seconds": int((moment - row.finished_at).total_seconds()),
            "affected": row.affected,
        }
    return ages


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


@router.get("/admin/recall-misses")
async def read_recall_misses(
    http: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> RecallMissesResponse:
    """What agents asked for and did not find, most wanted first.

    `recall_misses` has been filling up since decision 29 with nothing reading
    it. That was deliberate -- recording the signal is the irreversible half,
    and how to act on it is better designed against real rows than guesses --
    and this is the other half.

    The field that earns the endpoint is `best_score`. Forty candidates all
    just under the threshold and an empty corpus are the same empty answer to
    the caller and opposite instructions to us: the first says ranking is too
    strict, the second says the corpus has a hole. `candidates` and
    `best_score` are how a reader tells them apart.

    **Admin only, across every tenant.** An organization is not offered its own
    misses: the fingerprint includes `organization_id`, so per-tenant rows
    never merge and a self-view would be one `where` clause -- but recall is
    keyless, so an organization's own misses are the small anonymous-minus
    remainder of a table it already saw the empty answers from. Built when
    somebody asks, not before. What is *not* on offer at any point is one
    tenant's demand to another, which is why there is no organization filter
    parameter here to get wrong.

    Paging is limit/offset because this is a report read by a person a few
    times a week, not a feed. One row beyond the page is fetched to answer
    "is there more" without a second count query.
    """
    await limits.MISSES.check(db, limits.client_ip(http))
    await policy.authorize(principal, "admin.misses")
    rows = (
        (
            await db.execute(
                select(RecallMiss)
                # Demand first, then recency, then something total so a page
                # boundary landing inside a tie does not repeat or skip a row.
                .order_by(
                    RecallMiss.occurrences.desc(), RecallMiss.last_seen_at.desc(), RecallMiss.id
                )
                .offset(offset)
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    return RecallMissesResponse(
        misses=[
            RecallMissOut(
                intent=row.intent,
                terms=row.terms,
                environment=row.environment,
                constraints=row.constraints,
                candidates=row.candidates,
                best_score=row.best_score,
                occurrences=row.occurrences,
                organization_id=row.organization_id,
                first_seen_at=row.first_seen_at,
                last_seen_at=row.last_seen_at,
            )
            for row in rows[:limit]
        ],
        next_offset=offset + limit if len(rows) > limit else None,
    )


@router.post("/admin/organizations/{organization_id}/execution-tiers")
async def grant_execution_tiers(
    organization_id: str,
    request: GrantExecutionTiersRequest,
    http: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> ExecutionTiersResponse:
    """Approve one organization for the longer execution tiers.

    Decision 26 said a tier above `quick` is granted by an operator running an
    `INSERT` into `policies`, on the grounds that approval an endpoint can
    perform is approval an attacker can request, and named an admin-scoped
    endpoint as the obvious next step. This is it, and the reasoning survives
    intact: the caller cannot ask for a tier for themselves, they can only be
    given one by a key holding `admin`.

    `policy.authorize(principal, "admin.execution_tiers")` with no resource,
    following decision 39's revocation route exactly: it is a
    `MUTATING_ACTION`, so passing a row would make the engine demand an
    ownership a cross-tenant admin action cannot have.

    **Scoped to one organization**, named in the path, and the organization has
    to exist -- a typo becomes a 404 rather than a policy row nothing will ever
    read. **Deliberate**: the body is the exact set of tiers the organization
    ends up with, not a delta, so `{"tiers": []}` is how a grant is taken back
    and no grant is ever the accidental result of repeating a request.
    **Auditable**: `reason` is required and stored on the row alongside the
    granting agent and the time.

    What this cannot do is hand out an hour of compute on its own. `extended`
    additionally requires a verifier that checks what the run produced, checked
    per version at lease time by `resolve_execution_tier` -- an artifact that
    mines for an hour and exits 0 passes `exit_code`, which is why that second
    gate is not something an admin grant can wave through.

    The answer carries `effective` as well as `granted` because
    `granted_tiers` unions *every* policy row for the organization: a row an
    operator inserted by hand still grants, and this endpoint owns only its
    own. Where the two differ, `effective` is the truth.
    """
    # Cheap to serve and already behind ADMIN, so this is not protecting the
    # database. It bounds what a leaked admin key can do in an hour, and this
    # is the write that would be worth stealing one for.
    await limits.GRANT.check(db, limits.client_ip(http))
    await policy.authorize(principal, "admin.execution_tiers")

    organization = (
        await db.execute(select(Organization).where(Organization.id == organization_id))
    ).scalar_one_or_none()
    if organization is None:
        raise NotFound(f"organization {organization_id} not found")

    tiers = sorted({tier.value for tier in request.tiers})
    granted_at = now()
    # ponytail: read-then-write, with no unique index on (organization_id,
    # name) to make it an upsert -- adding one needs a migration. Two admins
    # granting the same organization at the same instant can leave two rows,
    # which over-grants rather than under-grants because `granted_tiers` unions
    # them; `effective` in the answer says so out loud. Ceiling: one admin at a
    # time. Upgrade path is the unique index plus ON CONFLICT.
    existing = (
        (
            await db.execute(
                select(Policy)
                .where(
                    Policy.organization_id == organization_id,
                    Policy.name == TIER_GRANT_POLICY,
                )
                .order_by(Policy.created_at)
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    rules: dict[str, Any] = {
        "execution_tiers": tiers,
        "granted_by": principal.agent_id,
        "reason": request.reason,
        "granted_at": granted_at.isoformat(),
    }
    if existing is None:
        db.add(
            Policy(
                id=ids.new_id(ids.POLICY),
                organization_id=organization_id,
                name=TIER_GRANT_POLICY,
                rules=rules,
                created_at=granted_at,
            )
        )
    else:
        existing.rules = rules
    await db.flush()

    effective = granted_tiers(
        (await db.execute(select(Policy.rules).where(Policy.organization_id == organization_id)))
        .scalars()
        .all()
    )
    # Committed before the answer goes out, for the same reason a credential
    # is: an operator told a tier is granted will run the thing immediately.
    await release(db)
    return ExecutionTiersResponse(
        organization_id=organization_id,
        granted=tiers,
        effective=sorted(effective),
        reason=request.reason,
        granted_by=principal.agent_id,
        granted_at=granted_at,
    )


@router.post("/admin/experiences/{experience_id}/quarantine")
async def set_quarantine(
    experience_id: str,
    request: QuarantineRequest,
    http: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> QuarantineResponse:
    """Withdraw one Experience from recall, or put it back.

    `quarantined` has been a status two places read and nothing wrote:
    `_promote` refuses to promote one and the recall pipeline hard-filters
    them, so the only way in was an operator typing an UPDATE against
    production. Decision 56 gives it two writers -- the evidence path, which
    acts on runs, and this one, which acts on everything runs cannot see.

    **Why a person still needs this** when `recompute` quarantines what rots:
    the reasons an Experience should stop being recommended are not all
    failures. An artifact with a credential baked into it works perfectly. So
    does one whose licence turns out to be wrong, or one that is doing
    something nobody wants done. No amount of run history detects any of that,
    and every one of them is urgent.

    `policy.authorize(principal, "admin.quarantine")` **with no resource**,
    following decision 39's revocation route and decision 53's grant route
    exactly: it is a `MUTATING_ACTION`, so passing the row would make the
    engine demand an ownership a cross-tenant admin action cannot have.

    **Both directions, one endpoint**, for the reason a tier grant is a set
    rather than a delta: `{"quarantined": false}` is how a withdrawal is taken
    back, so there is a way out that is not another hand-typed UPDATE.
    Releasing lands the Experience on `candidate`, never straight back on
    `verified` -- corroboration is re-earned through `recompute` like anything
    else, because a status restored by hand is exactly the self-attestation
    decision 41 exists to prevent.

    **Auditable**: `reason` is required and stored on the row next to the agent
    that decided and the time, the same way decision 53 stores a grant's. It
    also carries `manual`, which is load-bearing rather than decorative:
    `recompute` releases its own quarantines when the runs recover and never
    touches one a person imposed, so an operator's judgement cannot be undone
    by a lucky afternoon.
    """
    # Cheap to serve and already behind ADMIN, so this is not protecting the
    # database. It bounds what a leaked admin key can do in an hour, and this
    # is the write that takes capabilities away from every agent asking for
    # them -- the most damaging thing on the admin surface.
    await limits.QUARANTINE.check(db, limits.client_ip(http))
    await policy.authorize(principal, "admin.quarantine")

    experience = (
        await db.execute(select(Experience).where(Experience.id == experience_id))
    ).scalar_one_or_none()
    if experience is None:
        raise NotFound(f"experience {experience_id} not found")

    if request.quarantined:
        quarantine(experience, reason=request.reason, by=principal.agent_id, manual=True)
    else:
        experience.status = ExperienceStatus.CANDIDATE
        experience.quarantine = None
        experience.updated_at = now()
    await db.flush()
    # Committed before the answer goes out, for the same reason a revocation
    # is: an operator told a capability is withdrawn must not watch it come
    # back in the next recall.
    await release(db)
    return QuarantineResponse(
        experience_id=experience.id,
        status=str(experience.status),
        quarantine=experience.quarantine,
    )


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


async def _lineage_edges(db: DbSession, experience_ids: list[str]) -> list[tuple[str, str, str]]:
    """(source, relation, target) for the latest version of each id given.

    Only ever called with ids this caller has already been shown, so it needs
    no visibility predicate of its own. The one that matters is in
    `_visible_experiences`, which decides what a *target* resolves to.
    """
    if not experience_ids:
        return []
    rows = (
        await db.execute(
            select(ExperienceVersion.experience_id, ExperienceVersion.lineage)
            .join(Experience, Experience.id == ExperienceVersion.experience_id)
            .where(
                ExperienceVersion.experience_id.in_(experience_ids),
                ExperienceVersion.version == Experience.latest_version,
            )
        )
    ).all()
    lineages: dict[str, dict[str, Any]] = {source: dict(edges or {}) for source, edges in rows}
    return [
        (source, relation, str(lineages[source][relation]))
        for source in experience_ids
        if source in lineages
        for relation in LINEAGE_RELATIONS
        if lineages[source].get(relation)
    ]


async def _visible_experiences(
    db: DbSession, principal: Principal, experience_ids: list[str]
) -> dict[str, Experience]:
    """The subset of those ids this principal may see.

    `visibility_clause` is the same predicate recall filters on, reused rather
    than restated: tenant isolation stays one thing to audit. Everything else
    -- private to another organization, or simply never recorded -- is absent
    from the result, and absent looks identical either way.
    """
    if experience_ids:
        conditions: list[Any] = [
            Experience.id.in_(experience_ids),
            visibility_clause(principal),
        ]
        rows = (await db.execute(select(Experience).where(*conditions))).scalars().all()
        return {row.id: row for row in rows}
    return {}


def _lineage_node(
    source: str, relation: str, target: str, depth: int, row: Experience | None
) -> LineageNode:
    """One edge. An unresolvable target carries its id and nothing else."""
    if row is None:
        return LineageNode(
            from_experience_id=source,
            relation=relation,
            experience_id=target,
            depth=depth,
            resolved=False,
        )
    return LineageNode(
        from_experience_id=source,
        relation=relation,
        experience_id=target,
        depth=depth,
        resolved=True,
        # A stranger's bytes, on their way into an agent's context window, for
        # the same reason `_matches` neutralizes a recalled goal.
        goal=untrusted.neutralize(row.goal_statement),
        status=ExperienceStatus(row.status),
        verification_level=VerificationLevel(row.verification_level),
        latest_version=row.latest_version,
    )


@router.get("/experiences/{experience_id}/lineage", response_model_exclude_none=True)
async def get_experience_lineage(
    experience_id: str,
    db: DbSession,
    principal: CurrentPrincipal,
    depth: int = Query(default=3, ge=1, le=5, description="How many edges out to walk."),
) -> LineageResponse:
    """Walk what an Experience says it came from, and what it says it replaces.

    `lineage` has been written on every version since the first migration and
    read by nothing: six relations no response carried and no query traversed.
    This resolves them into the two facts an agent actually acts on -- is there
    something here that supersedes what I am about to run, and does the thing
    it improves still have better evidence than it does.

    **What a caller sees when an edge points somewhere they may not look.** A
    lineage id is free text written by whoever recorded the version and nothing
    validates it, so an edge can name another organization's private
    Experience. Targets are resolved through `visibility_clause`, and a target
    that does not come back -- private to someone else, or never recorded at
    all -- yields the identical node: the id, `resolved: false`, and no goal,
    no status, nothing. The two cases are indistinguishable on purpose. There
    is a real difference between "this does not exist" and "you may not see
    this", and answering it would make this endpoint an existence oracle for
    ids a caller was never shown.

    The id itself is not a leak: it appears in the `lineage` block of an
    Experience the caller can already read, which is where it came from.

    **Termination.** Breadth-first with a visited set, so each Experience
    appears once, by its shortest path -- `A supersedes B supersedes A` is
    writable today and stops after one node. `depth` is 1 to 5, default 3: the
    relations describe a fork-and-improve chain, and three hops is already
    further than any of them mean anything. Six relations per node makes depth
    5 worth 7776 nodes in the worst case, so the real bound is a budget of 200
    nodes, and `truncated` says when it ran out. Unresolved edges are never
    expanded, which is also what keeps another tenant's graph unwalkable.

    Not rate limited: it is authenticated, and it is at most ten small indexed
    queries against ids the caller already holds -- cheaper than the five
    recalls it takes to find them.
    """
    # The root is subject to the ordinary read rules, which decision 55 made
    # say less: another organization's Experience and one that was never
    # recorded are both 404, because the difference between them is exactly the
    # existence oracle the unresolved-edge rule above refuses to be. A 403 is
    # still possible, but only inside the caller's own organization.
    await ExperienceRepository(db).get(principal, experience_id)

    nodes: list[LineageNode] = []
    seen = {experience_id}
    frontier = [experience_id]
    truncated = False
    for level in range(1, depth + 1):
        if not frontier:
            break
        edges = [edge for edge in await _lineage_edges(db, frontier) if edge[2] not in seen]
        visible = await _visible_experiences(db, principal, [target for _, _, target in edges])
        frontier = []
        for source, relation, target in edges:
            if target in seen:
                continue
            if len(nodes) >= MAX_LINEAGE_NODES:
                truncated = True
                break
            seen.add(target)
            row = visible.get(target)
            nodes.append(_lineage_node(source, relation, target, level, row))
            if row is not None:
                frontier.append(target)
        if truncated:
            break
    return LineageResponse(
        experience_id=experience_id, depth=depth, nodes=nodes, truncated=truncated
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
    principal: Principal,
    query: RecallQuery,
) -> None:
    """Queue the miss row, if this was a miss.

    After the response, never during it: this is the demand signal, not the
    product, and a recall that fails because its telemetry failed would be the
    worst trade in the codebase.

    The caller's raw task is deliberately not passed on. `outcome.parsed` is
    everything the demand signal ever needed, and it is the only one of the two
    that cannot contain a customer's name. Decision 49.
    """
    if outcome.matches:
        return
    background.add_task(
        misses.record,
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
    _remember_miss(background, outcome, principal, query)
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
    _remember_miss(background, outcome, principal, query)
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
        # As recorded, unresolved, and only the relations that were set -- five
        # nulls on every experience read would cost every caller tokens to
        # learn nothing. `GET .../lineage` is what turns these into detail, and
        # it is the only thing that applies visibility to them.
        lineage={
            relation: untrusted.neutralize(str(value))
            for relation in LINEAGE_RELATIONS
            if (value := (version.lineage or {}).get(relation))
        },
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
