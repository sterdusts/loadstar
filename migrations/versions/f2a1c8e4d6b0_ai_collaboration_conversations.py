"""add durable AI collaboration conversations

Revision ID: f2a1c8e4d6b0
Revises: 7b6d0c1e9f4a
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2a1c8e4d6b0"
down_revision: str | None = "7b6d0c1e9f4a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_conversations",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("space_id", sa.String(), nullable=True),
        sa.Column("goal_id", sa.String(), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("provider_profile_id", sa.String(length=64), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("summary_through_sequence", sa.Integer(), nullable=False),
        sa.Column("working_plan", sa.JSON(), nullable=True),
        sa.Column("final_plan", sa.JSON(), nullable=True),
        sa.Column("learning_plan_id", sa.String(length=64), nullable=True),
        sa.Column("last_context_metadata", sa.JSON(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "summary_through_sequence >= 0",
            name=op.f("ck_ai_conversations_summary_through_sequence_nonnegative"),
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name=op.f("ck_ai_conversations_row_version_positive"),
        ),
        sa.CheckConstraint(
            "goal_id IS NULL OR space_id IS NOT NULL",
            name=op.f("ck_ai_conversations_goal_requires_space"),
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'ARCHIVED')",
            name=op.f("ck_ai_conversations_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["goal_id"],
            ["learning_goals.id"],
            name=op.f("fk_ai_conversations_goal_id_learning_goals"),
        ),
        sa.ForeignKeyConstraint(
            ["space_id"],
            ["knowledge_spaces.id"],
            name=op.f("fk_ai_conversations_space_id_knowledge_spaces"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_ai_conversations_user_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_conversations")),
    )
    op.create_index(
        op.f("ix_ai_conversations_user_id"),
        "ai_conversations",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_conversations_space_id"),
        "ai_conversations",
        ["space_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_conversations_goal_id"),
        "ai_conversations",
        ["goal_id"],
        unique=False,
    )

    op.create_table(
        "ai_conversation_messages",
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("structured_content", sa.JSON(), nullable=False),
        sa.Column("tool_call_id", sa.String(length=100), nullable=True),
        sa.Column("tool_name", sa.String(length=80), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("prompt_version", sa.String(length=80), nullable=True),
        sa.Column("message_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.CheckConstraint(
            "sequence_number >= 1",
            name=op.f("ck_ai_conversation_messages_sequence_number_positive"),
        ),
        sa.CheckConstraint(
            "role IN ('USER', 'ASSISTANT', 'TOOL')",
            name=op.f("ck_ai_conversation_messages_role_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["ai_conversations.id"],
            name=op.f("fk_ai_conversation_messages_conversation_id_ai_conversations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_conversation_messages")),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence_number",
            name="uq_ai_conversation_messages_sequence",
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "tool_call_id",
            name="uq_ai_conversation_messages_tool_call",
        ),
    )
    op.create_index(
        op.f("ix_ai_conversation_messages_conversation_id"),
        "ai_conversation_messages",
        ["conversation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_ai_conversation_messages_conversation_id"),
        table_name="ai_conversation_messages",
    )
    op.drop_table("ai_conversation_messages")
    op.drop_index(op.f("ix_ai_conversations_goal_id"), table_name="ai_conversations")
    op.drop_index(op.f("ix_ai_conversations_space_id"), table_name="ai_conversations")
    op.drop_index(op.f("ix_ai_conversations_user_id"), table_name="ai_conversations")
    op.drop_table("ai_conversations")
