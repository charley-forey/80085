"""Postgres implementations of the domain protocols (spec section 10).

Everything tenant-scoped goes through PolicyEngine before it is returned, so
there is exactly one path by which an object can leave the database.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from boobs_common import ids
from boobs_common.clock import now
from boobs_common.config import tier_for_duration
from boobs_common.errors import Conflict, Forbidden, NotFound, ValidationError
from boobs_domain.entities import DIGEST_RE, OCI_PINNED_RE
from boobs_domain.enums import ExperienceStatus, VerificationLevel
from boobs_domain.protocols import Principal, RecallQuery, SandboxResult
from boobs_retrieval.embedding import Embedder, embed_in_thread, embedder
from boobs_retrieval.intent import normalize
from boobs_retrieval.pipeline import RecallOutcome, recall, searchable_text
from boobs_schemas.api import RecordExperienceRequest
from boobs_schemas.tables import (
    Artifact,
    Execution,
    ExecutionEvent,
    Experience,
    ExperienceVersion,
)
from boobs_security.policy import ScopePolicyEngine


class ArtifactRepository:
    """Artifacts are content-addressed and shared across tenants: identical
    bytes are the same artifact no matter who registered them first."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def register(
        self, principal: Principal, reference: str, size_bytes: int | None = None
    ) -> Artifact:
        if not OCI_PINNED_RE.match(reference):
            raise ValidationError(
                "artifact reference must be pinned as repository@sha256:<digest>; "
                "tags are refused because the bytes behind them can change"
            )
        digest = reference.rsplit("@", 1)[1]
        if not DIGEST_RE.match(digest):
            raise ValidationError(f"malformed digest {digest!r}")

        existing = (
            await self._db.execute(select(Artifact).where(Artifact.digest == digest))
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        artifact = Artifact(
            id=ids.new_id(ids.ARTIFACT),
            type="oci",
            reference=reference,
            digest=digest,
            size_bytes=size_bytes,
            registered_by=principal.agent_id,
            created_at=now(),
        )
        self._db.add(artifact)
        await self._db.flush()
        return artifact

    async def resolve(self, artifact_id: str) -> Artifact:
        artifact = (
            await self._db.execute(select(Artifact).where(Artifact.id == artifact_id))
        ).scalar_one_or_none()
        if artifact is None:
            raise NotFound(f"artifact {artifact_id} not found")
        return artifact


class ExperienceRepository:
    def __init__(
        self,
        db: AsyncSession,
        policy: ScopePolicyEngine | None = None,
        model: Embedder | None = None,
    ) -> None:
        self._db = db
        self._policy = policy or ScopePolicyEngine()
        self._model = model or embedder()

    async def create(
        self, principal: Principal, request: RecordExperienceRequest
    ) -> tuple[Experience, ExperienceVersion]:
        await self._policy.authorize(principal, "experience.record")

        artifacts = ArtifactRepository(self._db)
        artifact = await artifacts.register(
            principal, request.artifact.reference, request.artifact.size_bytes
        )

        if request.experience_id:
            experience = await self.get(principal, request.experience_id)
            await self._policy.authorize(principal, "experience.record", experience)
            version_number = experience.latest_version + 1
        else:
            intent = request.goal.intent or normalize(request.goal.statement).canonical
            experience = Experience(
                id=ids.new_id(ids.EXPERIENCE),
                organization_id=principal.organization_id,
                goal_statement=request.goal.statement,
                goal_intent=intent,
                tags=list(request.goal.tags),
                status=ExperienceStatus.CANDIDATE,
                verification_level=VerificationLevel.UNVERIFIED,
                visibility=request.visibility,
                latest_version=0,
                created_by=principal.agent_id,
                created_at=now(),
                updated_at=now(),
            )
            self._db.add(experience)
            version_number = 1

        text = searchable_text(
            experience.goal_statement, experience.goal_intent, list(experience.tags)
        )
        embedding = (await embed_in_thread(self._model, [text]))[0]
        version = ExperienceVersion(
            id=ids.new_id(ids.VERSION),
            experience_id=experience.id,
            organization_id=principal.organization_id,
            version=version_number,
            artifact_id=artifact.id,
            command=list(request.command),
            inputs=request.inputs.model_dump() if request.inputs else None,
            outputs=request.outputs.model_dump() if request.outputs else None,
            verification=request.verification.model_dump() if request.verification else None,
            lineage=request.lineage.model_dump(),
            os=request.environment.os,
            architecture=request.environment.architecture,
            runtime=request.environment.runtime,
            runtime_version=request.environment.runtime_version,
            requires_network=request.constraints.network,
            required_capabilities=list(request.constraints.required_capabilities),
            # A declared duration is a request for a tier, not a grant of one:
            # whether the organization may actually use it is decided at lease
            # time, against a policy row nothing in the API can write.
            execution_tier=tier_for_duration(request.constraints.max_duration_seconds),
            search_text=text,
            embedding=embedding,
            created_by=principal.agent_id,
            created_at=now(),
        )
        self._db.add(version)
        experience.latest_version = version_number
        experience.updated_at = now()
        # Read before the flush: a failed flush expires every instance in the
        # session, and reading one back afterwards is a lazy load on a
        # transaction that can no longer run a statement -- which turns the
        # 409 below into the 500 it was written to replace.
        parent = experience.id
        try:
            await self._db.flush()
        except IntegrityError as exc:
            # Two recordings against the same Experience read `latest_version`
            # before either wrote it, so both computed the same next number and
            # uq_experience_version caught the loser. Unhandled that is a 500
            # on a request that was perfectly well formed. Same shape, and the
            # same answer, as a concurrent append in SqlEventStore below.
            #
            # ponytail: the caller retries and gets the next number. Serialising
            # instead -- SELECT latest_version ... FOR UPDATE -- would hold that
            # row lock across the embedding above, which is the slowest thing in
            # this method; take the number under a lock after the embedding if
            # concurrent recordings on one Experience ever stop being rare.
            raise Conflict(
                f"experience {parent} already has a version {version_number}; "
                "another recording won the race -- re-read and record again"
            ) from exc
        return experience, version

    async def get(self, principal: Principal, experience_id: str) -> Experience:
        """Every read of one Experience, and the only place existence is answered.

        `get_experience`, `execute_experience` and the lineage root all arrive
        here, so the rule below is stated once rather than per route.

        **The rule: the 403/404 distinction never crosses an organization.**
        An Experience owned by someone else and not visible to the caller is
        reported exactly as an id that was never recorded -- same error, same
        sentence, same status. Decision 52 built the lineage traversal so that
        an invisible edge and a dangling edge are byte-identical, and that
        guarantee was cosmetic while this path would answer the same question
        directly: private ids are not guessable, but they do not have to be
        guessed -- they are handed to their owner in plain text at record and
        they travel in logs, tickets and screenshots. Confirming one is the
        whole attack, and it is the thing refused here.

        Inside the caller's own organization the 403 is kept, because there it
        is worth more than it costs: an agent that cannot see a colleague's
        private Experience is told the id is real and the permission is not,
        rather than being sent hunting for a typo. The organization is the
        tenancy boundary the rest of this file defends; it is not a boundary
        this answer crosses.

        Scope is checked first and without the row, so a caller who lacks
        `experiences:read` gets the same 403 whether or not the id exists --
        otherwise the fix above would just move the oracle to anyone holding a
        write-only key.
        """
        await self._policy.authorize(principal, "experience.read")
        experience = (
            await self._db.execute(select(Experience).where(Experience.id == experience_id))
        ).scalar_one_or_none()
        if experience is None:
            raise NotFound(f"experience {experience_id} not found")
        try:
            await self._policy.authorize(principal, "experience.read", experience)
        except Forbidden:
            # Raised through the policy engine rather than by re-deciding
            # visibility here: `visible_to` stays the single definition of who
            # may see what, and this only chooses which of two answers the
            # refusal is allowed to be.
            if experience.organization_id == principal.organization_id:
                raise
            raise NotFound(f"experience {experience_id} not found") from None
        return experience

    async def get_version(
        self, principal: Principal, experience_id: str, version: int | None = None
    ) -> ExperienceVersion:
        experience = await self.get(principal, experience_id)
        wanted = version if version is not None else experience.latest_version
        row = (
            await self._db.execute(
                select(ExperienceVersion).where(
                    ExperienceVersion.experience_id == experience_id,
                    ExperienceVersion.version == wanted,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFound(f"experience {experience_id} has no version {wanted}")
        return row

    async def search(self, principal: Principal, query: RecallQuery) -> RecallOutcome:
        await self._policy.authorize(principal, "experience.recall")
        return await recall(self._db, principal, query, self._model)


class ExecutionRepository:
    def __init__(self, db: AsyncSession, policy: ScopePolicyEngine | None = None) -> None:
        self._db = db
        self._policy = policy or ScopePolicyEngine()

    async def create(self, execution: Execution) -> Execution:
        self._db.add(execution)
        await self._db.flush()
        return execution

    async def by_idempotency_key(self, principal: Principal, key: str) -> Execution | None:
        """The execution some earlier request with this key already created.

        Scoped to the caller's organization by the same predicate as the unique
        index behind it, so a token cannot be used to observe -- or collide
        with -- another tenant's runs.
        """
        return (
            await self._db.execute(
                select(Execution).where(
                    Execution.organization_id == principal.organization_id,
                    Execution.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()

    async def get(self, principal: Principal, execution_id: str) -> Execution:
        execution = (
            await self._db.execute(select(Execution).where(Execution.id == execution_id))
        ).scalar_one_or_none()
        if execution is None:
            raise NotFound(f"execution {execution_id} not found")
        # Executions are never cross-tenant readable: they are the caller's own
        # run of someone else's Experience, and may contain the caller's data.
        # Note which answer that is -- the same 404, not a 403. This path
        # settled the question before `get` above did, and `get` was brought
        # into line with it rather than the other way round.
        if execution.organization_id != principal.organization_id:
            raise NotFound(f"execution {execution_id} not found")
        return execution


class SqlEventStore:
    """Append-only execution event stream (spec section 20)."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def append(
        self, execution_id: str, event_type: str, payload: dict[str, Any]
    ) -> ExecutionEvent:
        next_sequence = (
            await self._db.execute(
                select(func.coalesce(func.max(ExecutionEvent.sequence), 0) + 1).where(
                    ExecutionEvent.execution_id == execution_id
                )
            )
        ).scalar_one()
        event = ExecutionEvent(
            id=ids.new_id(ids.EVENT),
            execution_id=execution_id,
            sequence=int(next_sequence),
            event_type=event_type,
            payload=payload,
            created_at=now(),
        )
        self._db.add(event)
        try:
            await self._db.flush()
        except Exception as exc:  # concurrent append raced us on the sequence
            raise Conflict(f"event sequence conflict for {execution_id}") from exc
        return event

    async def stream(self, execution_id: str) -> AsyncIterator[ExecutionEvent]:
        rows = (
            await self._db.execute(
                select(ExecutionEvent)
                .where(ExecutionEvent.execution_id == execution_id)
                .order_by(ExecutionEvent.sequence)
            )
        ).scalars()
        for row in rows:
            yield row


def sandbox_failure_reason(result: SandboxResult) -> str | None:
    if result.error:
        return result.error
    if result.exit_code not in (0, None):
        return f"exit_code={result.exit_code}"
    return None
