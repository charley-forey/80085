"""job run heartbeat

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-23

Nothing outside Railway's own dashboard recorded that a scheduled job ran.
Railway reports a crashed deployment when a job exits non-zero, but only for a
service that still exists -- so the quiet failure, a cron service never created
or since deleted, raises no alarm at all: evidence stops being reconciled and
every health check stays green.

One row per job, overwritten on each success. Not a history: what is actionable
is "when did this last succeed", and an audit log of cron ticks would need a
retention job of its own.

Decision 63.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_runs",
        # The job's name as `80085-scheduler <name>` takes it, which is also
        # the key in scheduler.JOBS. One row per job, so the primary key is the
        # whole index this needs.
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        # What the job did, so a heartbeat that is alive but doing nothing is
        # distinguishable from one that is working.
        sa.Column("affected", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("job_runs")
