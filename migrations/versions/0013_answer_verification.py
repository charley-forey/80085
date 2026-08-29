"""an answer serves its own agent, and the company only once a human says so

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-28

An answer is typed into one agent's chat by whoever was watching it work. That
is the right capture point -- they are already there, and routing it through a
channel would make halting cost more than guessing, which is the one thing that
must never be true.

But one person's sentence in one session is not a fact about the company, and
since decision 74 an agent told to defer believes what it is handed. So an
unverified answer serves only the agent that asked; the organisation inherits it
when a second human says it should.

Decision 83.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("answers", sa.Column("asked_by_agent", sa.String(64)))
    op.add_column("answers", sa.Column("verified_at", sa.DateTime(timezone=True)))
    op.add_column("answers", sa.Column("verified_by", sa.String(200)))


def downgrade() -> None:
    op.drop_column("answers", "verified_by")
    op.drop_column("answers", "verified_at")
    op.drop_column("answers", "asked_by_agent")
