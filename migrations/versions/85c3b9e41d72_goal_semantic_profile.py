"""persist constrained goal semantic profiles

Revision ID: 85c3b9e41d72
Revises: 4e2f7a9c1b30
Create Date: 2026-08-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "85c3b9e41d72"
down_revision: str | None = "4e2f7a9c1b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Null means "use the product baseline for this goal's GoalIntent".  Leaving the
    # column nullable preserves every existing goal without inventing AI-authored copy.
    with op.batch_alter_table("learning_goals") as batch_op:
        batch_op.add_column(sa.Column("semantic_profile", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("learning_goals") as batch_op:
        batch_op.drop_column("semantic_profile")
