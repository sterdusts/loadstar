"""add contextual AI assistant conversation scope

Revision ID: a4c8e2f71b90
Revises: f2a1c8e4d6b0
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4c8e2f71b90"
down_revision: str | None = "f2a1c8e4d6b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing unbound conversations retain their planning semantics. Conversations
    # already bound to a concrete goal are promoted below so their durable history
    # remains visible in the project's global assistant.
    with op.batch_alter_table("ai_conversations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "purpose",
                sa.String(length=24),
                nullable=False,
                server_default="PLANNING",
            )
        )
        batch_op.add_column(sa.Column("context_key", sa.String(length=320), nullable=True))
        batch_op.add_column(
            sa.Column(
                "context_snapshot",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch_op.create_check_constraint(
            "purpose_valid",
            "purpose IN ('PLANNING', 'PAGE_ASSISTANT', 'PROJECT_ASSISTANT')",
        )
        batch_op.create_check_constraint(
            "assistant_context_key_required",
            "purpose = 'PLANNING' OR context_key IS NOT NULL",
        )
        batch_op.create_check_constraint(
            "project_assistant_scope_required",
            "purpose != 'PROJECT_ASSISTANT' OR (space_id IS NOT NULL AND goal_id IS NOT NULL)",
        )
        batch_op.create_check_constraint(
            "page_assistant_scope_forbidden",
            "purpose != 'PAGE_ASSISTANT' OR (space_id IS NULL AND goal_id IS NULL)",
        )
    op.execute(
        sa.text(
            "UPDATE ai_conversations "
            "SET purpose = 'PROJECT_ASSISTANT', context_key = 'project:' || goal_id "
            "WHERE space_id IS NOT NULL AND goal_id IS NOT NULL"
        )
    )
    op.create_index(
        op.f("ix_ai_conversations_context_key"),
        "ai_conversations",
        ["context_key"],
        unique=False,
    )
    op.create_index(
        "ix_ai_conversations_user_purpose_context",
        "ai_conversations",
        ["user_id", "purpose", "context_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ai_conversations_user_purpose_context", table_name="ai_conversations")
    op.drop_index(op.f("ix_ai_conversations_context_key"), table_name="ai_conversations")
    with op.batch_alter_table("ai_conversations") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_ai_conversations_page_assistant_scope_forbidden"),
            type_="check",
        )
        batch_op.drop_constraint(
            op.f("ck_ai_conversations_project_assistant_scope_required"),
            type_="check",
        )
        batch_op.drop_constraint(
            op.f("ck_ai_conversations_assistant_context_key_required"),
            type_="check",
        )
        batch_op.drop_constraint(
            op.f("ck_ai_conversations_purpose_valid"),
            type_="check",
        )
        batch_op.drop_column("context_snapshot")
        batch_op.drop_column("context_key")
        batch_op.drop_column("purpose")
