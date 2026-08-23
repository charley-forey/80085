"""quarantine gets a reason, evidence gets a checkpoint

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-23

Two columns, for the two halves of decisions 56 and 57.

`experiences.quarantine` is where a withdrawal says why. `quarantined` has been
a status two places read and nothing wrote, so the only way in was an operator
typing an UPDATE against production and there was nowhere at all to record the
cause. The column holds the reason, who decided, when, and whether a person
decided -- the last of which is what stops an operator's judgement being undone
by a lucky run of successes.

`execution_stats.checkpoint` is where the evidence computation remembers how
far it read, plus the three things the existing columns cannot carry forward:
which organizations have proven the version, a bounded sample of recent
durations, and the recent outcomes the staleness policy reads. It is a cache of
a pure function of immutable rows, which is why it is nullable and why every
existing row starts null: the first recompute after this deploys rebuilds from
source and fills it in, and dropping it at any time costs one full rescan and
changes no number.

Chained onto 0009 (`0009_execution_cached`), verified with
`ls migrations/versions/` and `alembic heads` printing exactly one line.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "experiences",
        sa.Column("quarantine", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "execution_stats",
        sa.Column("checkpoint", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    # Both are safe to drop. Losing the checkpoint costs one full rescan per
    # version and no accuracy; losing `quarantine` leaves anything already
    # quarantined quarantined, with nothing left saying why -- so read the
    # column before running this.
    op.drop_column("execution_stats", "checkpoint")
    op.drop_column("experiences", "quarantine")
