"""verifier strength in evidence

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-23

Ranking was verifier-blind: a trivial `exit 0` produced the same confidence as
a byte-exact sha256 match. Evidence now records the strongest verifier that
actually passed for a version, so ranking can discount the weak ones.

`execution_stats` is a cache of a computation over immutable rows, so existing
rows need no backfill beyond the default -- the next verification recomputes
them, and `recompute` rebuilds them exactly from source at any time.

**Numbered 0006 because 0005 was taken.** This was written while 0005 was still
unmerged, so it chained onto 0004 -- the real head at the time -- rather than
onto a revision Alembic could not resolve. 0005 has since landed and this now
chains onto it, which is what keeps `alembic heads` at one line. The rule the
detour illustrates: a migration numbered for a parent that does not exist yet
is not a plan, it is a fork waiting to happen.
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
    op.add_column(
        "execution_stats",
        sa.Column(
            "verification_level",
            sa.String(32),
            nullable=False,
            server_default="unverified",
        ),
    )


def downgrade() -> None:
    op.drop_column("execution_stats", "verification_level")
