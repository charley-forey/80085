"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-22

Creates the tables in spec section 11 plus the two things the ORM cannot
express: the pgvector extension and the append-only triggers that make
"historical execution records must remain immutable" a property of the
database rather than a promise in a docstring.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TERMINAL = ("succeeded", "failed", "timeout", "rejected")

APPEND_ONLY_FN = """
CREATE OR REPLACE FUNCTION boobs_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% is append-only; % refused', TG_TABLE_NAME, TG_OP;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "organizations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "agents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(64),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(64),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "agent_id",
            sa.String(64),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("scopes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("type", sa.String(32), nullable=False, server_default="oci"),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("digest", sa.String(80), nullable=False, unique=True, index=True),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("registered_by", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "experiences",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(64),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("goal_statement", sa.Text(), nullable=False),
        sa.Column("goal_intent", sa.String(200), nullable=False, index=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("verification_level", sa.String(32), nullable=False, server_default="unverified"),
        sa.Column("visibility", sa.String(32), nullable=False, server_default="private"),
        sa.Column("latest_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "experience_versions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "experience_id",
            sa.String(64),
            sa.ForeignKey("experiences.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("organization_id", sa.String(64), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "artifact_id",
            sa.String(64),
            sa.ForeignKey("artifacts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("command", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("inputs", postgresql.JSONB()),
        sa.Column("outputs", postgresql.JSONB()),
        sa.Column("verification", postgresql.JSONB()),
        sa.Column("lineage", postgresql.JSONB(), nullable=False),
        sa.Column("os", sa.String(32), nullable=False, server_default="linux"),
        sa.Column("architecture", sa.String(32), nullable=False, server_default="amd64"),
        sa.Column("runtime", sa.String(64)),
        sa.Column("runtime_version", sa.String(32)),
        sa.Column(
            "requires_network", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("required_capabilities", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', search_text)", persisted=True),
        ),
        sa.Column("embedding", Vector(384)),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("experience_id", "version", name="uq_experience_version"),
    )
    op.create_index("ix_versions_tsv", "experience_versions", ["tsv"], postgresql_using="gin")
    op.create_index(
        "ix_versions_filters",
        "experience_versions",
        ["os", "architecture", "runtime", "requires_network"],
    )
    op.execute(
        "CREATE INDEX ix_versions_embedding ON experience_versions "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "executions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("organization_id", sa.String(64), nullable=False, index=True),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("experience_id", sa.String(64), nullable=False, index=True),
        sa.Column("experience_version_id", sa.String(64), nullable=False),
        sa.Column("artifact_digest", sa.String(80), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("exit_code", sa.Integer()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("output_key", sa.Text()),
        sa.Column("logs_key", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_executions_version_status", "executions", ["experience_version_id", "status"]
    )

    op.create_table(
        "execution_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("execution_id", sa.String(64), nullable=False, index=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("execution_id", "sequence", name="uq_event_sequence"),
    )

    op.create_table(
        "verifications",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("execution_id", sa.String(64), nullable=False, index=True),
        sa.Column("experience_version_id", sa.String(64), nullable=False, index=True),
        sa.Column("verifier", sa.String(64), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("level", sa.String(32), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "policies",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(64),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("rules", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "execution_stats",
        sa.Column("experience_version_id", sa.String(64), primary_key=True),
        sa.Column("experience_id", sa.String(64), nullable=False, index=True),
        sa.Column("successful_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("median_duration_ms", sa.Integer()),
        sa.Column("p95_duration_ms", sa.Integer()),
        sa.Column("success_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("distinct_organizations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_modes", postgresql.JSONB(), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    _install_immutability_guards()


def _install_immutability_guards() -> None:
    op.execute(APPEND_ONLY_FN)
    for table in ("experience_versions", "execution_events", "verifications"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only "
            f"BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION boobs_append_only()"
        )

    terminal = ", ".join(f"'{s}'" for s in TERMINAL)
    op.execute(
        "CREATE OR REPLACE FUNCTION boobs_execution_guard() RETURNS trigger AS $$\n"
        "BEGIN\n"
        "    IF TG_OP = 'DELETE' THEN\n"
        "        RAISE EXCEPTION 'executions are immutable; DELETE refused';\n"
        "    END IF;\n"
        f"    IF OLD.status IN ({terminal}) THEN\n"
        "        RAISE EXCEPTION 'execution % is already terminal (%); UPDATE refused',\n"
        "            OLD.id, OLD.status;\n"
        "    END IF;\n"
        "    RETURN NEW;\n"
        "END;\n"
        "$$ LANGUAGE plpgsql;"
    )
    op.execute(
        "CREATE TRIGGER executions_guard BEFORE UPDATE OR DELETE ON executions "
        "FOR EACH ROW EXECUTE FUNCTION boobs_execution_guard()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS executions_guard ON executions")
    for table in ("experience_versions", "execution_events", "verifications"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS boobs_execution_guard()")
    op.execute("DROP FUNCTION IF EXISTS boobs_append_only()")
    for table in (
        "execution_stats",
        "policies",
        "verifications",
        "execution_events",
        "executions",
        "experience_versions",
        "experiences",
        "artifacts",
        "api_keys",
        "agents",
        "organizations",
    ):
        op.drop_table(table)
