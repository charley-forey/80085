"""The recall pipeline (spec section 12).

    task -> intent normalization -> hard filters -> lexical + vector ->
    candidate merge -> ranking -> top N

Hard filters run in SQL so an incompatible artifact is never ranked, never
returned, and never executed. Ranking then answers "will this work for me".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from boobs_domain.entities import Evidence, RecallCandidate
from boobs_domain.enums import Compatibility, ExperienceStatus, Visibility
from boobs_domain.protocols import Principal, RecallQuery
from boobs_observability import counter, tracer
from boobs_retrieval import ranking
from boobs_retrieval.embedding import Embedder, embed_in_thread, embedder
from boobs_retrieval.intent import Intent, normalize
from boobs_schemas.tables import ExecutionStat, Experience, ExperienceVersion

CANDIDATE_POOL = 50

# Recall used to report one aggregate `took_ms` and nothing else, so a slow
# recall was indistinguishable from a slow embedder or a slow database. These
# are the four stages, timed separately. With no OTLP endpoint configured the
# tracer is the API's no-op and none of this allocates a span.
_tracer = tracer(__name__)
_recalls = counter("recall_requests", "recall queries, attributed by whether anything matched")


@dataclass(frozen=True)
class RecallOutcome:
    """What recall returned, and what it had to work with to get there.

    `matches` alone cannot tell a question nobody has answered from one that
    was nearly answered, and that difference is the whole value of a recorded
    miss: `considered` 0 means nothing remotely close exists, while
    `considered` 40 with `best_score` 0.29 means the corpus is one hair under
    the threshold. Carried out of the pipeline rather than logged here because
    retrieval reads the database; it does not write to it.
    """

    matches: list[RecallCandidate]
    parsed: Intent
    considered: int  # survived hard filters and both retrieval halves
    cleared: int  # of those, how many scored at or above MIN_SCORE
    best_score: float  # best final score seen, threshold or not


@dataclass(frozen=True)
class Row:
    version_id: str
    experience_id: str
    version: int
    goal: str
    intent: str
    runtime: str | None
    runtime_version: str | None
    requires_network: bool
    required_capabilities: tuple[str, ...]


def visibility_clause(principal: Principal) -> object:
    """Who may see what. Mirrors boobs_security.policy.visible_to; both
    exist because one is a SQL predicate and one is an in-memory check."""
    return or_(
        Experience.visibility == Visibility.PUBLIC,
        and_(
            Experience.organization_id == principal.organization_id,
            Experience.visibility == Visibility.ORGANIZATION,
        ),
        and_(
            Experience.organization_id == principal.organization_id,
            Experience.visibility == Visibility.PRIVATE,
            Experience.created_by == principal.agent_id,
        ),
    )


def base_query(principal: Principal, query: RecallQuery) -> Select[tuple[ExperienceVersion]]:
    """Hard compatibility filters (spec section 12).

    Anything rejected here is not merely down-ranked -- running it could not
    work, so it must not be offered.
    """
    environment = query.environment
    constraints = query.constraints

    conditions: list[Any] = [
        visibility_clause(principal),
        Experience.status.notin_([ExperienceStatus.DEPRECATED, ExperienceStatus.QUARANTINED]),
        # Only the current version of each Experience is recallable; older
        # versions stay executable by exact id, but are not recommended.
        ExperienceVersion.version == Experience.latest_version,
        ExperienceVersion.os == environment.os,
        ExperienceVersion.architecture == environment.architecture,
    ]

    if environment.runtime:
        conditions.append(
            or_(
                ExperienceVersion.runtime.is_(None),
                ExperienceVersion.runtime == environment.runtime,
            )
        )

    if not constraints.network:
        conditions.append(ExperienceVersion.requires_network.is_(False))

    # required_capabilities must be a subset of what the caller offers.
    conditions.append(
        text("experience_versions.required_capabilities <@ :caps").bindparams(
            caps=list(constraints.required_capabilities)
        )
    )

    return (
        select(ExperienceVersion)
        .join(Experience, Experience.id == ExperienceVersion.experience_id)
        .where(and_(*conditions))
    )


def compatibility(row: ExperienceVersion, query: RecallQuery) -> Compatibility:
    """How well the caller's environment matches. Filters have already removed
    the impossible cases, so this grades the survivors."""
    environment = query.environment
    if row.os != environment.os or row.architecture != environment.architecture:
        return Compatibility.NONE
    if row.runtime and environment.runtime and row.runtime != environment.runtime:
        return Compatibility.NONE
    if row.runtime_version and environment.runtime_version:
        if row.runtime_version == environment.runtime_version:
            return Compatibility.HIGH
        wanted = environment.runtime_version.split(".")
        have = row.runtime_version.split(".")
        return Compatibility.HIGH if wanted[:1] == have[:1] else Compatibility.PARTIAL
    return Compatibility.HIGH


async def _lexical(
    db: AsyncSession, principal: Principal, query: RecallQuery, task_text: str
) -> dict[str, float]:
    """Returns id -> ts_rank_cd. The score matters, not only the ordering:
    ranking needs to know *how well* something matched, not just that it did."""
    tsquery = func.websearch_to_tsquery("english", task_text)
    rank = func.ts_rank_cd(ExperienceVersion.tsv, tsquery)
    statement = (
        base_query(principal, query)
        .add_columns(rank.label("rank"))
        .where(ExperienceVersion.tsv.op("@@")(tsquery))
        .order_by(rank.desc())
        .limit(CANDIDATE_POOL)
    )
    rows = (await db.execute(statement)).all()
    return {row[0].id: float(row.rank) for row in rows}


async def _vector(
    db: AsyncSession, principal: Principal, query: RecallQuery, vector: list[float]
) -> dict[str, float]:
    """Returns id -> cosine similarity in [0, 1]."""
    distance = ExperienceVersion.embedding.cosine_distance(vector)
    statement = (
        base_query(principal, query)
        .add_columns(distance.label("distance"))
        .where(ExperienceVersion.embedding.is_not(None))
        .order_by(distance)
        .limit(CANDIDATE_POOL)
    )
    rows = (await db.execute(statement)).all()
    return {row[0].id: max(0.0, 1.0 - float(row.distance)) for row in rows}


def searchable_text(goal_statement: str, intent: str, tags: list[str]) -> str:
    """The text indexed for a version. Written once at record time so recall
    never has to reconstruct it."""
    return " ".join([goal_statement, intent, intent.replace("_", " "), *tags])


async def recall(
    db: AsyncSession,
    principal: Principal,
    query: RecallQuery,
    model: Embedder | None = None,
) -> RecallOutcome:
    model = model or embedder()
    parsed = normalize(query.task)
    task_text = f"{query.task} {parsed.canonical.replace('_', ' ')}"

    with _tracer.start_as_current_span("recall") as span:
        span.set_attribute("recall.intent", parsed.canonical)

        with _tracer.start_as_current_span("recall.embed") as embed:
            # Named because it is the stage most likely to be the answer: the
            # hashing fallback is fast and wrong, fastembed is slow and right.
            embed.set_attribute("recall.embedder", type(model).__name__)
            task_vector = (await embed_in_thread(model, [task_text]))[0]

        with _tracer.start_as_current_span("recall.lexical") as stage:
            lexical = await _lexical(db, principal, query, task_text)
            stage.set_attribute("recall.candidates", len(lexical))

        with _tracer.start_as_current_span("recall.vector") as stage:
            vector = await _vector(db, principal, query, task_vector)
            stage.set_attribute("recall.candidates", len(vector))

        with _tracer.start_as_current_span("recall.rank"):
            outcome = await _merge_and_rank(db, query, parsed, lexical, vector)

        span.set_attribute("recall.matches", len(outcome.matches))

    # recall_match_rate (spec section 33) is matched / total over this counter.
    _recalls.add(1, {"matched": bool(outcome.matches)})
    return outcome


async def _merge_and_rank(
    db: AsyncSession,
    query: RecallQuery,
    parsed: Intent,
    lexical: dict[str, float],
    vector: dict[str, float],
) -> RecallOutcome:
    """Fuse the two candidate lists, score the survivors, return the best.

    Split out of `recall` so each retrieval stage sits in its own span; the
    ranking logic is unchanged.
    """
    intent = parsed.canonical
    # RRF decides which candidates to consider; it deliberately does not decide
    # how relevant they are. RRF scores are positional, so the top candidate
    # always looks perfect -- which is how a popular Experience could win a
    # query it does not answer.
    fused = ranking.reciprocal_rank_fusion([ranking.order(lexical), ranking.order(vector)])
    if not fused:
        return RecallOutcome(matches=[], parsed=parsed, considered=0, cleared=0, best_score=0.0)

    candidate_ids = sorted(fused, key=lambda key: fused[key], reverse=True)[:CANDIDATE_POOL]

    rows = (
        await db.execute(
            select(ExperienceVersion, Experience, ExecutionStat)
            .join(Experience, Experience.id == ExperienceVersion.experience_id)
            .outerjoin(
                ExecutionStat,
                ExecutionStat.experience_version_id == ExperienceVersion.id,
            )
            .where(ExperienceVersion.id.in_(candidate_ids))
        )
    ).all()

    candidates: list[tuple[float, RecallCandidate]] = []
    best_score = 0.0
    for version, experience, stat in rows:
        compat = compatibility(version, query)
        relevance = ranking.relevance_of(lexical.get(version.id), vector.get(version.id))
        # An exact intent match is strong evidence that two differently worded
        # tasks are the same task. It raises how well this MATCHES -- it says
        # nothing about whether it WORKS, so it must not touch the evidence.
        if experience.goal_intent == intent:
            relevance = min(1.0, relevance + ranking.INTENT_MATCH_BONUS)
        evidence = _evidence(stat)
        signals = ranking.Signals(
            relevance=relevance,
            compatibility=compat,
            successful_runs=evidence.successful_runs,
            failed_runs=evidence.failed_runs,
            last_verified_at=evidence.last_verified_at,
            median_duration_ms=evidence.median_duration_ms,
            requires_network=version.requires_network,
            required_capabilities=tuple(version.required_capabilities or ()),
        )
        final, confidence = ranking.score(signals)
        # Recorded before the threshold is applied: a miss that scored 0.29 is
        # a different fact about the corpus than one that scored nothing.
        best_score = max(best_score, final)
        if final < ranking.MIN_SCORE:
            # Better to return nothing and let the agent solve it normally
            # than to hand back a confident wrong capability.
            continue
        evidence.confidence = confidence
        candidates.append(
            (
                final,
                RecallCandidate(
                    experience_id=experience.id,
                    version=version.version,
                    experience_version_id=version.id,
                    goal=experience.goal_statement,
                    relevance=round(relevance, 4),
                    compatibility=compat,
                    confidence=round(confidence, 4),
                    successful_runs=evidence.successful_runs,
                    recommendation=ranking.recommend(final, compat),
                    evidence=evidence,
                    requires_network=version.requires_network,
                ),
            )
        )

    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return RecallOutcome(
        matches=[candidate for _, candidate in candidates[: query.limit]],
        parsed=parsed,
        considered=len(rows),
        cleared=len(candidates),
        best_score=round(best_score, 4),
    )


def _evidence(stat: ExecutionStat | None) -> Evidence:
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
