"""rate limit windows

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-23

Rate limit counters lived in a process-local dict, so the effective limit was
multiplied by the replica count and reset on every deploy. One row per caller
per limit per window moves the count somewhere every replica can see it,
without bringing Redis back for one counter.

The table is not tenant-owned: it is keyed by client address, because the
callers worth limiting are the ones with no key yet.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rate_limits",
        # "<what>:<client address>".
        sa.Column("bucket", sa.String(300), primary_key=True),
        # Epoch seconds, aligned down to the window length. The primary key is
        # the whole index this needs: every check is one lookup by both
        # columns, and the periodic sweep scans a table that is small by
        # construction.
        sa.Column("window_start", sa.BigInteger(), primary_key=True),
        sa.Column("hits", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("rate_limits")
