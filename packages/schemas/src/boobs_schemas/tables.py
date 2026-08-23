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
    scripts/rebuild_evidence.py regenerates it from the source rows.
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
    failure_modes: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    """

    __tablename__ = "recall_misses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Deduplication key over (canonical intent, normalized keywords, filters).
    # Recall is keyless and public, so without this one script could write a
    # row per request forever; with it, a thousand rephrasings of the same
    # unmet need collapse to one row and a counter.
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    organization_id: Mapped[str | None] = mapped_column(String(64), index=True)
    task: Mapped[str] = mapped_column(Text, nullable=False)
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
