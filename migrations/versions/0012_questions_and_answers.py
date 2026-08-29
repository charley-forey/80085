"""halts recorded as questions, and the answers that close them

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-28

The corpus this system was built around was written by us, guessing what agents
would need, and the benchmarks showed 36 of 37 entries were things they did not
need (decision 81). These two tables cannot make that mistake: every question
originates in a real agent that genuinely could not proceed and refused to
guess, so the corpus can only grow in directions something actually asked for.

An answer is not evidence and is not modelled as evidence. Everything else here
earns trust by accumulating verified runs from distinct parties, which a single
tenant cannot do -- there is one party (decision 79). What one organisation has
instead is an accountable human, so an answer carries a name rather than a
count, and supersession rather than deletion, because an answer that turned out
wrong is the row somebody most needs to find.

Decision 82.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 384


def upgrade() -> None:
    op.create_table(
        "questions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("organization_id", sa.String(64), nullable=False, index=True),
        sa.Column("agent_id", sa.String(64)),
        sa.Column("need", sa.Text(), nullable=False),
        sa.Column("context", sa.JSON()),
        sa.Column("embedding", Vector(EMBEDDING_DIM)),
        sa.Column("asked", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_asked_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Recall is always scoped to one tenant, so the index leads with the
    # organization: a question is a fact about one company's decisions and is
    # never matched across the boundary.
    op.create_index("ix_questions_org_asked", "questions", ["organization_id", "asked"])

    op.create_table(
        "answers",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("question_id", sa.String(64), nullable=False, index=True),
        sa.Column("organization_id", sa.String(64), nullable=False, index=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("answered_by", sa.String(200), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_by", sa.String(64)),
    )


def downgrade() -> None:
    op.drop_index("ix_questions_org_asked", table_name="questions")
    op.drop_table("answers")
    op.drop_table("questions")
