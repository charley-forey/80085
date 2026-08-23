"""executions record whether they were replayed

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-23

`CachingRuntime` has always stamped `SandboxResult.cached` on a replay, and the
HTTPS boundary has always thrown it away, so the API could not tell a run from
a replay and `recompute` counted both as independent verification runs. This
column is where the flag lands, and `Execution.cached.is_(False)` in
`recompute` is what makes it mean something -- see decision 51.

Every existing row is `false`, which is exactly true: the cache has been off by
default since it was written, and a replay could not have been reported anyway.
No backfill, no interpretation.

Chained onto 0008 (`0008_misses_without_task_text`), verified with
`ls migrations/versions/` and `alembic heads` printing exactly one line.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "executions",
        sa.Column("cached", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    # Dropping this does not un-count anything: recompute reads the column, so
    # a downgrade returns to counting replays as runs. Turn the worker cache
    # off first.
    op.drop_column("executions", "cached")
