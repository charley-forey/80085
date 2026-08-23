"""worker leases

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-23

The execution queue moves from Redis into Postgres so that an off-platform
worker needs nothing but HTTPS to the API. See DECISIONS.md entry 17.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("executions", sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
    op.add_column("executions", sa.Column("leased_by", sa.String(64)))
    op.add_column(
        "executions", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0")
    )
    # The claim query orders queued work by age; this index is what keeps
    # SELECT ... FOR UPDATE SKIP LOCKED cheap as the table grows.
    op.create_index("ix_executions_queue", "executions", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_executions_queue", table_name="executions")
    op.drop_column("executions", "attempts")
    op.drop_column("executions", "leased_by")
    op.drop_column("executions", "lease_expires_at")
