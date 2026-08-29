"""when nobody answers, when an answer was wrong, and who it reached

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-29

Three gaps that only appear once the loop is real.

**Nobody answers.** Every design so far assumed the human replies. In practice a
question sits for three days and the agent is blocked, and a blocked agent is
the most likely reason somebody switches the halt off -- restoring exactly the
silent wrong answers the halt existed to stop. `assumed` is the escape hatch and
it is deliberately not silent: an agent that must proceed records what it
assumed, and every number downstream is traceable to it. We cannot make the
human faster; we can make the guess visible.

**An answer was wrong.** Superseding fixes the future and says nothing about the
past, so "what did we get wrong because of this" had no answer. `served` is the
blast radius. `disputed_*` is somebody saying it caused damage -- distinct from
supersession, because whoever noticed the damage is usually not whoever knows
the right answer, and a disputed answer must stop being served before anybody
works that out.

**Does it converge?** The thesis is that questions get answered once and stop
recurring. If an organisation has a long tail of near-unique conventions, `asked`
never climbs and the loop never repays its cost. Both counters above make that
measurable rather than assumed.

Decision 84.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("questions", sa.Column("assumed", sa.Text()))
    op.add_column("questions", sa.Column("assumed_at", sa.DateTime(timezone=True)))
    op.add_column(
        "answers", sa.Column("served", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("answers", sa.Column("disputed_at", sa.DateTime(timezone=True)))
    op.add_column("answers", sa.Column("disputed_by", sa.String(200)))
    op.add_column("answers", sa.Column("disputed_reason", sa.Text()))


def downgrade() -> None:
    for column in ("disputed_reason", "disputed_by", "disputed_at", "served"):
        op.drop_column("answers", column)
    op.drop_column("questions", "assumed_at")
    op.drop_column("questions", "assumed")
