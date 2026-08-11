"""add editable versioned learning path revisions

Revision ID: 7b6d0c1e9f4a
Revises: 85c3b9e41d72
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7b6d0c1e9f4a"
down_revision: str | None = "85c3b9e41d72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing rows are the first immutable revisions.  LEGACY preserves their
    # provenance instead of pretending that a user or the current planner authored them.
    with op.batch_alter_table("learning_paths") as batch_op:
        batch_op.add_column(sa.Column("parent_path_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("base_active_path_id", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "validity_status",
                sa.String(length=20),
                nullable=False,
                server_default="VALID",
            )
        )
        batch_op.add_column(
            sa.Column(
                "origin",
                sa.String(length=32),
                nullable=False,
                server_default="LEGACY",
            )
        )
        batch_op.add_column(
            sa.Column("row_version", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(
            sa.Column("change_summary", sa.Text(), nullable=False, server_default="")
        )
        batch_op.add_column(sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_learning_paths_parent_path_id_learning_paths",
            "learning_paths",
            ["parent_path_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_learning_paths_base_active_path_id_learning_paths",
            "learning_paths",
            ["base_active_path_id"],
            ["id"],
        )
        batch_op.create_check_constraint("generation_positive", "generation_number >= 1")
        batch_op.create_check_constraint("row_version_positive", "row_version >= 1")
    op.create_index(
        op.f("ix_learning_paths_parent_path_id"),
        "learning_paths",
        ["parent_path_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_learning_paths_base_active_path_id"),
        "learning_paths",
        ["base_active_path_id"],
        unique=False,
    )
    op.execute(
        sa.text(
            "UPDATE learning_paths SET activated_at = generated_at "
            "WHERE status = 'ACTIVE' AND activated_at IS NULL"
        )
    )
    # Old binaries did not have a database-level single-active invariant.  If a
    # legacy database contains duplicates, retain the newest generation and keep
    # the older rows as history before creating the partial unique index.
    op.execute(
        sa.text(
            "UPDATE learning_paths AS old SET status = 'SUPERSEDED', "
            "superseded_at = COALESCE(old.superseded_at, old.generated_at) "
            "WHERE old.status = 'ACTIVE' AND EXISTS ("
            "SELECT 1 FROM learning_paths AS newer "
            "WHERE newer.goal_id = old.goal_id AND newer.status = 'ACTIVE' AND ("
            "newer.generation_number > old.generation_number OR "
            "(newer.generation_number = old.generation_number AND newer.id > old.id)"
            ")"
            ")"
        )
    )
    op.create_index(
        "uq_learning_paths_goal_active",
        "learning_paths",
        ["goal_id"],
        unique=True,
        sqlite_where=sa.text("status = 'ACTIVE'"),
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    with op.batch_alter_table("learning_path_nodes") as batch_op:
        batch_op.add_column(
            sa.Column("preferred_order", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("action_kind", sa.String(length=24), nullable=False, server_default="LEARN")
        )
        batch_op.add_column(sa.Column("stage", sa.String(length=160), nullable=True))
        batch_op.add_column(
            sa.Column("priority", sa.Integer(), nullable=False, server_default="50")
        )
        batch_op.add_column(sa.Column("estimated_minutes", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("is_deferred", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column("user_note", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("source", sa.String(length=32), nullable=False, server_default="LEGACY")
        )
        batch_op.create_check_constraint("preferred_order_nonnegative", "preferred_order >= 0")
        batch_op.create_check_constraint("priority_range", "priority BETWEEN 0 AND 100")
        batch_op.create_check_constraint(
            "estimated_minutes_nonnegative",
            "estimated_minutes IS NULL OR estimated_minutes >= 0",
        )
    op.execute(sa.text("UPDATE learning_path_nodes SET preferred_order = sequence_number"))


def downgrade() -> None:
    with op.batch_alter_table("learning_path_nodes") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_learning_path_nodes_estimated_minutes_nonnegative"), type_="check"
        )
        batch_op.drop_constraint(op.f("ck_learning_path_nodes_priority_range"), type_="check")
        batch_op.drop_constraint(
            op.f("ck_learning_path_nodes_preferred_order_nonnegative"), type_="check"
        )
        batch_op.drop_column("source")
        batch_op.drop_column("user_note")
        batch_op.drop_column("is_deferred")
        batch_op.drop_column("is_pinned")
        batch_op.drop_column("estimated_minutes")
        batch_op.drop_column("priority")
        batch_op.drop_column("stage")
        batch_op.drop_column("action_kind")
        batch_op.drop_column("preferred_order")

    op.drop_index("uq_learning_paths_goal_active", table_name="learning_paths")
    op.drop_index(op.f("ix_learning_paths_base_active_path_id"), table_name="learning_paths")
    op.drop_index(op.f("ix_learning_paths_parent_path_id"), table_name="learning_paths")
    with op.batch_alter_table("learning_paths") as batch_op:
        batch_op.drop_constraint(op.f("ck_learning_paths_row_version_positive"), type_="check")
        batch_op.drop_constraint(op.f("ck_learning_paths_generation_positive"), type_="check")
        batch_op.drop_constraint(
            op.f("fk_learning_paths_base_active_path_id_learning_paths"),
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            op.f("fk_learning_paths_parent_path_id_learning_paths"),
            type_="foreignkey",
        )
        batch_op.drop_column("activated_at")
        batch_op.drop_column("change_summary")
        batch_op.drop_column("row_version")
        batch_op.drop_column("origin")
        batch_op.drop_column("validity_status")
        batch_op.drop_column("base_active_path_id")
        batch_op.drop_column("parent_path_id")
