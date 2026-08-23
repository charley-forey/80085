"""execute idempotency

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-23

A client that times out on POST /v1/experiences/{id}/execute and retries used
to buy a second Execution row and a second real sandbox run. The key is the
receipt for an attempt: whoever inserts it first wins the unique index, and
the retry is answered with the execution that already exists.

Adding a nullable column and an index is DDL, so it touches no row and does
not disturb the append-only guards on `executions`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("executions", sa.Column("idempotency_key", sa.String(200)))
    # Partial: rows without a key -- which is nearly all of them, since the
    # field is optional -- must not collide with each other. Scoped by
    # organization so one tenant's token cannot collide with another's, and
    # cannot be used to probe whether another tenant used the same one.
    op.create_index(
        "ux_executions_idempotency",
        "executions",
        ["organization_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_executions_idempotency", table_name="executions")
    op.drop_column("executions", "idempotency_key")
