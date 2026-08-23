"""add durable AI conversation attachments

Revision ID: b7d1f4a8c2e6
Revises: a6c9e2f4b7d1
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7d1f4a8c2e6"
down_revision: str | None = "a6c9e2f4b7d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_conversation_attachments",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=True),
        sa.Column("message_id", sa.String(), nullable=True),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("extraction_metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('INDEXED', 'PARTIAL', 'UNSUPPORTED', 'ERROR')",
            name="ck_ai_conversation_attachments_status_valid",
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["ai_conversations.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["ai_conversation_messages.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "storage_key",
            name=op.f("uq_ai_conversation_attachments_storage_key"),
        ),
    )
    op.create_index(
        "ix_ai_conversation_attachments_user_id",
        "ai_conversation_attachments",
        ["user_id"],
    )
    op.create_index(
        "ix_ai_conversation_attachments_conversation_id",
        "ai_conversation_attachments",
        ["conversation_id"],
    )
    op.create_index(
        "ix_ai_conversation_attachments_message_id",
        "ai_conversation_attachments",
        ["message_id"],
    )
    op.create_index(
        "ix_ai_conversation_attachments_owner_conversation",
        "ai_conversation_attachments",
        ["user_id", "conversation_id"],
    )
    op.create_index(
        "ix_ai_conversation_attachments_owner_message",
        "ai_conversation_attachments",
        ["user_id", "message_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_conversation_attachments_owner_message",
        table_name="ai_conversation_attachments",
    )
    op.drop_index(
        "ix_ai_conversation_attachments_owner_conversation",
        table_name="ai_conversation_attachments",
    )
    op.drop_index(
        "ix_ai_conversation_attachments_message_id",
        table_name="ai_conversation_attachments",
    )
    op.drop_index(
        "ix_ai_conversation_attachments_conversation_id",
        table_name="ai_conversation_attachments",
    )
    op.drop_index(
        "ix_ai_conversation_attachments_user_id",
        table_name="ai_conversation_attachments",
    )
    op.drop_table("ai_conversation_attachments")
