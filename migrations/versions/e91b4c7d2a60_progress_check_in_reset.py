"""allow explicit zero-score progress reset markers

Revision ID: e91b4c7d2a60
Revises: d8f0e31b7a24
Create Date: 2026-08-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e91b4c7d2a60"
down_revision: str | None = "d8f0e31b7a24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("node_progress_check_ins") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_node_progress_check_ins_score_range"),
            type_="check",
        )
        batch_op.create_check_constraint("score_range", "score BETWEEN 0 AND 10")


def downgrade() -> None:
    # Reset markers cannot be represented by the previous constraint.  Remove
    # only zero markers; positive daily check-ins and their history remain.
    op.execute("DELETE FROM node_progress_check_ins WHERE score = 0")
    with op.batch_alter_table("node_progress_check_ins") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_node_progress_check_ins_score_range"),
            type_="check",
        )
        batch_op.create_check_constraint("score_range", "score BETWEEN 1 AND 10")
