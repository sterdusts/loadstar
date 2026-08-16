"""add durable progress check-in attachments

Revision ID: e4a7b9c2d5f1
Revises: c3d5e7f9a1b2
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4a7b9c2d5f1"
down_revision: str | None = "c3d5e7f9a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "progress_check_in_attachments",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("check_in_id", sa.String(), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "size_bytes >= 0", name="ck_progress_check_in_attachments_size_bytes_nonnegative"
        ),
        sa.ForeignKeyConstraint(
            ["check_in_id"],
            ["node_progress_check_ins.id"],
            name="fk_progress_check_in_attachments_check_in_id_node_progress_check_ins",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_progress_check_in_attachments_user_id_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_progress_check_in_attachments"),
        sa.UniqueConstraint("storage_key", name="uq_progress_check_in_attachments_storage_key"),
    )
    op.create_index(
        "ix_progress_check_in_attachments_check_in_id",
        "progress_check_in_attachments",
        ["check_in_id"],
    )
    op.create_index(
        "ix_progress_check_in_attachments_user_id",
        "progress_check_in_attachments",
        ["user_id"],
    )
    op.create_index(
        "ix_progress_check_in_attachments_owner_check_in",
        "progress_check_in_attachments",
        ["user_id", "check_in_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_progress_check_in_attachments_owner_check_in",
        table_name="progress_check_in_attachments",
    )
    op.drop_index(
        "ix_progress_check_in_attachments_user_id",
        table_name="progress_check_in_attachments",
    )
    op.drop_index(
        "ix_progress_check_in_attachments_check_in_id",
        table_name="progress_check_in_attachments",
    )
    op.drop_table("progress_check_in_attachments")
