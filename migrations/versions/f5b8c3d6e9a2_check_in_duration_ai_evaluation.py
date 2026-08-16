"""add check-in duration and AI evaluation

Revision ID: f5b8c3d6e9a2
Revises: e4a7b9c2d5f1
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f5b8c3d6e9a2"
down_revision: str | None = "e4a7b9c2d5f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("node_progress_check_ins") as batch_op:
        batch_op.add_column(
            sa.Column("duration_minutes", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(sa.Column("ai_evaluation", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("ai_evaluated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("node_progress_check_ins") as batch_op:
        batch_op.drop_column("ai_evaluated_at")
        batch_op.drop_column("ai_evaluation")
        batch_op.drop_column("duration_minutes")
