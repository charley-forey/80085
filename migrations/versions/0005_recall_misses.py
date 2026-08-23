"""recall misses

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-23

Chained onto 0004 (`0004_execution_tiers`), which is the head on main --
verified with `git ls-tree origin/main migrations/versions/` and
`alembic heads`, not assumed.

This file was written when 0003 was head and three branches were each holding
an unmerged 0004. It was numbered 0005 rather than 0004 because two files
sharing a revision id is a hard Alembic failure the moment both land, while a
gap in the sequence costs nothing. That reasoning survived contact: 0004 landed
as the execution tiers migration, and this became a second head pointing at
0003 until `down_revision` was moved here.

The lesson worth keeping is that numbering and chaining are separate problems,
and only the second one can fork the graph. A rebase has to re-check what head
actually is -- `alembic heads` printing one line is the check, and it is cheap
enough that there is no excuse for merging a fork.

What this stores is user-supplied text. `docs/security.md` says so out loud,
along with the retention window, because quietly retaining what people typed
is not a thing to discover from a schema.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recall_misses",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        # No foreign key: recall is keyless, so most rows are anonymous and the
        # anonymous principal has no organizations row to reference.
        sa.Column("organization_id", sa.String(64)),
        sa.Column("task", sa.Text, nullable=False),
        sa.Column("intent", sa.String(200), nullable=False),
        sa.Column("environment", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("constraints", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("candidates", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cleared", sa.Integer, nullable=False, server_default="0"),
        sa.Column("best_score", sa.Float, nullable=False, server_default="0"),
        sa.Column("occurrences", sa.Integer, nullable=False, server_default="1"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    # The bound on the table. An upsert on this index turns a flood of
    # rephrasings of one unmet need into one row and a counter.
    op.create_index("ux_recall_misses_fingerprint", "recall_misses", ["fingerprint"], unique=True)
    op.create_index("ix_recall_misses_organization_id", "recall_misses", ["organization_id"])
    # Demand is read by intent; retention is swept by last_seen_at.
    op.create_index("ix_recall_misses_intent", "recall_misses", ["intent"])
    op.create_index("ix_recall_misses_last_seen_at", "recall_misses", ["last_seen_at"])


def downgrade() -> None:
    op.drop_table("recall_misses")
