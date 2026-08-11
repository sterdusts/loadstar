"""persist a goal-specific intent mode

Revision ID: 4e2f7a9c1b30
Revises: c6e9d431a02f
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4e2f7a9c1b30"
down_revision: str | None = "c6e9d431a02f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The server default backfills existing goals and also protects older application
    # binaries during a rolling upgrade.  LEARN preserves the behavior of all legacy goals.
    with op.batch_alter_table("learning_goals") as batch_op:
        batch_op.add_column(
            sa.Column(
                "intent_mode",
                sa.String(length=24),
                nullable=False,
                server_default="LEARN",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("learning_goals") as batch_op:
        batch_op.drop_column("intent_mode")
