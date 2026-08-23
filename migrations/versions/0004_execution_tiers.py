"""execution tiers

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-23

A longer run is a bigger weapon, so length becomes a tier that an operator
grants rather than a number the recorder picks. Everything that already exists
is `quick`, which is what it was already getting.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "experience_versions",
        sa.Column("execution_tier", sa.String(16), nullable=False, server_default="quick"),
    )


def downgrade() -> None:
    op.drop_column("experience_versions", "execution_tier")
