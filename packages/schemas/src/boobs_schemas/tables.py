"""SQLAlchemy tables (spec section 11).

Rules encoded here rather than in prose:
  * every tenant-owned row carries organization_id;
  * experience_versions, executions, execution_events and verifications are
    append-only -- enforced by triggers in the migration, not by convention;
  * artifacts are stored pinned by digest and are globally deduplicated.

Retrieval columns (search_text, tsv, embedding) live on experience_versions
rather than in a separate experience_embeddings table so that hard
compatibility filters and ranking happen in one query with no join.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 384  # BAAI/bge-small-en-v1.5

JSONType = JSONB().with_variant(JSON(), "sqlite")
ArrayText = ARRAY(Text).with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    pass


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ApiKey(Base):
    """Only the hash is stored. The plaintext key exists once, at creation."""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    scopes: Mapped[list[str]] = mapped_column(ArrayText, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Artifact(Base):
    """Immutable executable. Deduplicated on digest across all tenants: the
    same bytes are the same artifact, whoever registered them first."""

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False, default="oci")
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    digest: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    registered_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Experience(Base):
    __tablename__ = "experiences"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    goal_statement: Mapped[str] = mapped_column(Text, nullable=False)
    goal_intent: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    tags: Mapped[list[str]] = mapped_column(ArrayText, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    verification_level: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unverified"
    )
    # Why this is quarantined, who did it and when -- null unless it is.
    # `quarantined` used to be a status nothing wrote, so the only way in was an
    # operator's UPDATE and there was nowhere to say why. Kept on the row it
    # justifies, the way decision 53 keeps a tier grant's reason, because a
    # withdrawal nobody can explain is one nobody will confidently reverse.
    # `manual` is the flag that stops an operator's judgement being undone by a
    # lucky run of successes (DECISIONS 56).
    quarantine: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="private")
    latest_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExperienceVersion(Base):
    __tablename__ = "experience_versions"
    __table_args__ = (
        UniqueConstraint("experience_id", "version", name="uq_experience_version"),
        Index("ix_versions_tsv", "tsv", postgresql_using="gin"),
        Index("ix_versions_filters", "os", "architecture", "runtime", "requires_network"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    experience_id: Mapped[str] = mapped_column(
        ForeignKey("experiences.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_id: Mapped[str] = mapped_column(
        ForeignKey("artifacts.id", ondelete="RESTRICT"), nullable=False
    )

    command: Mapped[list[str]] = mapped_column(ArrayText, nullable=False, default=list)
    inputs: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    outputs: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    verification: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    lineage: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)

    # Flattened for hard filters (spec section 12); full objects stay in JSON.
    os: Mapped[str] = mapped_column(String(32), nullable=False, default="linux")
    architecture: Mapped[str] = mapped_column(String(32), nullable=False, default="amd64")
    runtime: Mapped[str | None] = mapped_column(String(64))
    runtime_version: Mapped[str | None] = mapped_column(String(32))
    requires_network: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    required_capabilities: Mapped[list[str]] = mapped_column(
        ArrayText, nullable=False, default=list
    )
    # How long this version may run for, as a tier rather than a number: a
    # number here would be an attacker-chosen timeout. Defaults to `quick`, so
    # everything recorded before tiers existed keeps today's limits.
    execution_tier: Mapped[str] = mapped_column(
        String(16), nullable=False, default="quick", server_default="quick"
    )

    search_text: Mapped[str] = mapped_column(Text, nullable=False)
    tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', search_text)", persisted=True)
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Execution(Base):
    __tablename__ = "executions"
    __table_args__ = (
        Index("ix_executions_version_status", "experience_version_id", "status"),
        Index("ix_executions_queue", "status", "created_at"),
        # Partial, so the overwhelming majority of rows -- which carry no key --
        # are not constrained against each other. Scoped by organization because
        # one tenant's retry token must not collide with another's.
        Index(
            "ux_executions_idempotency",
            "organization_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    experience_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    experience_version_id: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_digest: Mapped[str] = mapped_column(String(80), nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    exit_code: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    output_key: Mapped[str | None] = mapped_column(Text)
    logs_key: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)

    # Replayed by the worker's cache rather than executed (DECISIONS 20, 51).
    # The row is a true record that a caller asked and got an answer, so it is
    # kept; it is not a record that anything ran, so `evidence.recompute`
    # excludes it from both counts. Defaults false: a worker that does not send
    # the flag is describing a run it actually performed.
    cached: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    # A client that times out and retries must not buy a second sandbox run.
    # The row is the receipt: whoever inserts it first wins the unique index,
    # and the retry is answered with the execution that already exists.
    idempotency_key: Mapped[str | None] = mapped_column(String(200))

    # Lease bookkeeping: the executions table is the queue (see DECISIONS.md 17).
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    leased_by: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExecutionEvent(Base):
    __tablename__ = "execution_events"
    __table_args__ = (UniqueConstraint("execution_id", "sequence", name="uq_event_sequence"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Verification(Base):
    __tablename__ = "verifications"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    experience_version_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    verifier: Mapped[str] = mapped_column(String(64), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    level: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Policy(Base):
    """Per-organization overrides of sandbox and permission defaults."""

    __tablename__ = "policies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    rules: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExecutionStat(Base):
    """Denormalised counters kept in step with the immutable rows.

    Evidence is *derivable* from executions/verifications; this table exists so
    recall does not aggregate the whole history on every query. It is a cache:
    `boobs_reputation.evidence.rebuild` regenerates it from the source rows,
    and the scheduler's `evidence` job runs that on a clock.
    """

    __tablename__ = "execution_stats"

    experience_version_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    experience_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    successful_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    median_duration_ms: Mapped[int | None] = mapped_column(Integer)
    p95_duration_ms: Mapped[int | None] = mapped_column(Integer)
    success_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    distinct_organizations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Strongest verifier that has actually passed for this version. Ranking
    # discounts confidence by it: an `exit 0` is not a sha256 match.
    verification_level: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unverified", server_default="unverified"
    )
    failure_modes: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # How far the last computation read, plus the few things the columns above
    # cannot carry forward: which organizations have proven it, a bounded
    # sample of recent durations, and the recent win/lose outcomes the
    # staleness policy reads. It exists so a new run costs the rows since the
    # last one instead of the whole history (DECISIONS 57). Null means "no
    # checkpoint", which is always safe: the next call rebuilds from source.
    checkpoint: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RecallMiss(Base):
    """What agents asked for and did not find.

    The one dataset this system cannot backfill. A recall that returned nothing
    used to leave no trace, so every day without this row was a day of demand
    data thrown away -- and demand for a capability nobody has recorded is the
    most direct signal available about what should exist next.

    Not tenant-scoped the way every other table is: recall needs no credential,
    so `organization_id` is null for most rows and that is fine. It is
    attribution where attribution happens to exist, never a requirement, and
    there is deliberately no foreign key -- the anonymous principal owns no
    organizations row to point at.

    A row is written only when nothing cleared MIN_SCORE. `candidates` and
    `best_score` are what separate "nothing remotely close" from "one hair
    under the threshold".

    **It holds no free text.** It used to store the raw task, untruncated,
    from callers who supplied no credential. Nothing read it and the demand
    signal never needed it: the fingerprint dedups on the *normalized* intent,
    and what a gap is called is `intent` plus `terms`, both drawn from closed
    tables in our own source. Decision 49.
    """

    __tablename__ = "recall_misses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Deduplication key over (canonical intent, normalized keywords, filters).
    # Recall is keyless and public, so without this one script could write a
    # row per request forever; with it, a thousand rephrasings of the same
    # unmet need collapse to one row and a counter.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    organization_id: Mapped[str | None] = mapped_column(String(64), index=True)
    # What is left of the asker's words after everything we did not write
    # ourselves is thrown away: a space-joined subset of the action and format
    # labels in `boobs_retrieval.intent`. Nothing a caller types can reach this
    # column -- see `misses.vocabulary` and decision 49. It replaces `task`,
    # which held the raw, untruncated request text.
    terms: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    intent: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    environment: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    constraints: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    candidates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cleared: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    best_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class RateLimit(Base):
    """One counter per caller, per limit, per time window.

    Belongs to no tenant: it is keyed by client address, and the callers that
    matter most to limit are the ones with no key yet. Written on the hot path
    of a keyless endpoint, so it is deliberately one row and one statement --
    see apps/api/src/boobs_api/limits.py for the shape and its ceilings.
    """

    __tablename__ = "rate_limits"

    # "<what>:<client address>", so limits of different lengths never share a
    # row and one cutoff expires all of them.
    bucket: Mapped[str] = mapped_column(String(300), primary_key=True)
    # Epoch seconds, aligned down to the window length.
    window_start: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class JobRun(Base):
    """When each scheduled job last finished. One row per job, overwritten.

    Railway is the scheduler and it does report a crashed deployment when a job
    exits non-zero -- but only for a service that still exists. The failure
    this table exists for is quieter: a cron service never created, deleted, or
    given a schedule that does not fire. Nothing crashes, no alarm is raised,
    and evidence simply stops being reconciled while every dashboard stays
    green.

    `scripts/smoke.py` could not check it before this. The obvious candidate,
    `execution_stats.updated_at`, is also written by the execution path, so a
    recent value proves only that somebody ran something -- a check that passes
    for the wrong reason, which is the failure mode this project keeps finding.

    Deliberately not a history. What is actionable is "when did this last
    succeed", and a growing audit log of cron ticks would need a retention job
    of its own. Decision 63.
    """

    __tablename__ = "job_runs"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # What the job did, so a heartbeat that is alive but doing nothing is
    # distinguishable from one that is working.
    affected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Question(Base):
    """A halt: something an agent could not determine and refused to guess at.

    The corpus this system was built around was written by us, guessing what
    agents would need, and the benchmarks showed 36 of 37 entries were things
    they did not need (DECISIONS 81). This table cannot make that mistake. Every
    row originates in a real agent, on real data, that genuinely could not
    proceed -- so the corpus can only grow in directions something actually
    asked for.

    `need` is the agent's own words for what it would have to be told. It is
    free text from a caller and is treated as such everywhere it is rendered.

    Tenant-scoped and it matters more here than anywhere else in the schema. A
    question is "which reading of an end date does *this company* use", which is
    a fact about one organisation's decisions and never leaves it.

    `asked` counts how many times an agent halted on this same question. It is
    the demand signal the recall-miss table only approximates: a question asked
    forty times and never answered is the most expensive row in the database.
    """

    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    agent_id: Mapped[str | None] = mapped_column(String(64))
    need: Mapped[str] = mapped_column(Text, nullable=False)
    # What the agent was doing when it stopped. Enough for a human to answer
    # without going and asking which file this was about.
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    asked: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_asked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # What an agent decided to assume when nobody had answered in time.
    #
    # The design until now assumed the human replies. In practice a question
    # sits for three days and the agent is blocked, and a blocked agent is the
    # most likely reason somebody switches the halt off -- at which point the
    # silent wrong answers come straight back and we have achieved nothing.
    #
    # So the escape hatch exists, and it is deliberately not silent. An agent
    # that must proceed records what it assumed, and every number downstream of
    # that assumption is traceable to it. We cannot make the human faster. We
    # can make the guess visible, which is the entire thesis applied to our own
    # failure mode.
    assumed: Mapped[str | None] = mapped_column(Text)
    assumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Answer(Base):
    """What somebody said, once, so nothing has to ask again.

    Deliberately not evidence. Everything else in this schema earns trust by
    accumulating verified runs from distinct parties, and inside one
    organisation that is unavailable by construction -- there is only one party
    (DECISIONS 79). What a single tenant has instead is an accountable human,
    so an answer carries a name rather than a count.

    That is weaker than corroboration in one way, since one person can be wrong,
    and stronger in another: they can be asked why, and the mistake has an
    owner. It is also how every internal runbook already works.

    `superseded_by` rather than deletion, because an answer that turned out
    wrong is the most interesting row in the table and destroying it destroys
    the audit trail at exactly the moment somebody needs it.
    """

    __tablename__ = "answers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    question_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Who is accountable. Free text on purpose: it is a name a colleague can
    # walk to, not a foreign key into an identity system we do not have.
    answered_by: Mapped[str] = mapped_column(String(200), nullable=False)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    superseded_by: Mapped[str | None] = mapped_column(String(64))

    # Who asked, so an unverified answer can serve them and nobody else.
    #
    # An answer is typed into one agent's chat by whoever was watching it work.
    # That is the right place to capture it -- they are already there, and
    # waiting on a channel would make halting cost more than guessing. But one
    # person's sentence in one session is not yet a fact about the company, and
    # since decision 74 an agent told to defer believes what it is handed.
    #
    # So there are two tiers. Unverified serves the agent that asked, which is
    # where the answer was already going to be used anyway. Verified serves the
    # organisation, and requires a second human to say so.
    asked_by_agent: Mapped[str | None] = mapped_column(String(64))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[str | None] = mapped_column(String(200))

    # How many agents have acted on this, which is its blast radius.
    #
    # An answer that turns out wrong is worse than no answer, because agents are
    # instructed to defer to it (DECISIONS 74) and nothing downstream questions
    # what they produce. Superseding it fixes the future and says nothing about
    # the past, so the first question anybody asks -- "what did we get wrong
    # because of this" -- had no answer at all.
    served: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Somebody says this produced a wrong result. Not a deletion and not a
    # supersession: those assert what is true instead, and a dispute is
    # frequently raised by whoever noticed the damage rather than whoever knows
    # the right answer. A disputed answer stops being served immediately.
    disputed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disputed_by: Mapped[str | None] = mapped_column(String(200))
    disputed_reason: Mapped[str | None] = mapped_column(Text)
