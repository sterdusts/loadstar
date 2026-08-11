"""add durable daily node progress check-ins

Revision ID: d8f0e31b7a24
Revises: a4c8e2f71b90
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8f0e31b7a24"
down_revision: str | None = "a4c8e2f71b90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "node_progress_check_ins",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("goal_id", sa.String(), nullable=False),
        sa.Column("node_id", sa.String(), nullable=False),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("check_in_date", sa.Date(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("row_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "row_version >= 1", name=op.f("ck_node_progress_check_ins_row_version_positive")
        ),
        sa.CheckConstraint(
            "score BETWEEN 1 AND 10", name=op.f("ck_node_progress_check_ins_score_range")
        ),
        sa.ForeignKeyConstraint(
            ["goal_id"],
            ["learning_goals.id"],
            name=op.f("fk_node_progress_check_ins_goal_id_learning_goals"),
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["knowledge_nodes.id"],
            name=op.f("fk_node_progress_check_ins_node_id_knowledge_nodes"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_node_progress_check_ins_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_node_progress_check_ins")),
        sa.UniqueConstraint(
            "user_id",
            "goal_id",
            "node_id",
            "check_in_date",
            name=op.f("uq_node_progress_check_ins_user_id"),
        ),
    )
    op.create_index(
        op.f("ix_node_progress_check_ins_goal_id"),
        "node_progress_check_ins",
        ["goal_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_node_progress_check_ins_node_id"),
        "node_progress_check_ins",
        ["node_id"],
        unique=False,
    )
    op.create_index(
        "ix_node_progress_check_ins_scope_date",
        "node_progress_check_ins",
        ["user_id", "goal_id", "node_id", "check_in_date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_node_progress_check_ins_user_id"),
        "node_progress_check_ins",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_node_progress_check_ins_user_id"), table_name="node_progress_check_ins")
    op.drop_index("ix_node_progress_check_ins_scope_date", table_name="node_progress_check_ins")
    op.drop_index(op.f("ix_node_progress_check_ins_node_id"), table_name="node_progress_check_ins")
    op.drop_index(op.f("ix_node_progress_check_ins_goal_id"), table_name="node_progress_check_ins")
    op.drop_table("node_progress_check_ins")
