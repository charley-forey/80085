"""recall misses stop holding the raw task text

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-23

`recall_misses.task` held the caller's request verbatim and untruncated, from
callers who supplied no credential, and nothing ever read it. `terms` replaces
it with the closed-vocabulary residue of the same task -- see decision 49.

**Existing rows are dealt with, not grandfathered.** `terms` cannot be
backfilled: it comes from `boobs_retrieval.intent.normalize`, which is Python,
and reimplementing that tokenizer in SQL to recover three words per row would
be a much larger and much more wrong change than losing them. Old rows keep
their `intent`, their filters and their counters, and get an empty `terms`.
Everything they lose is the thing this migration exists to stop keeping.

ponytail: `DROP COLUMN` removes the text from the logical table at once, but
Postgres leaves the bytes in the heap until the table is next rewritten. A
`VACUUM FULL recall_misses` cannot run here -- Alembic wraps a migration in a
transaction and VACUUM refuses one -- so run it by hand after deploying if the
dead bytes matter as much as the live ones did. The table is small by
construction, so it takes a moment and an exclusive lock nobody will notice.

Chained onto 0007 (`0007_verifier_strength`), verified with
`ls migrations/versions/` and `alembic heads` printing exactly one line, not
assumed -- which is the lesson 0005 and 0007 each paid for in their own way.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "recall_misses",
        sa.Column("terms", sa.String(120), nullable=False, server_default=""),
    )
    op.drop_column("recall_misses", "task")


def downgrade() -> None:
    # The text is gone and cannot come back, so the column returns empty. A
    # downgrade that invented plausible task strings would be worse than one
    # that admits the data was deleted on purpose.
    op.add_column(
        "recall_misses",
        sa.Column("task", sa.Text, nullable=False, server_default=""),
    )
    op.drop_column("recall_misses", "terms")
