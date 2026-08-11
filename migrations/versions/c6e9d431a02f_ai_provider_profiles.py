"""add AI provider profiles

Revision ID: c6e9d431a02f
Revises: 09446b55cadc
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c6e9d431a02f"
down_revision: str | None = "09446b55cadc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_provider_profiles",
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("key_last4", sa.String(length=4), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_ai_provider_profiles_owner_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_provider_profiles")),
        sa.UniqueConstraint(
            "owner_id",
            "display_name",
            name=op.f("uq_ai_provider_profiles_owner_id"),
        ),
    )
    op.create_index(
        op.f("ix_ai_provider_profiles_owner_id"),
        "ai_provider_profiles",
        ["owner_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_ai_provider_profiles_owner_id"),
        table_name="ai_provider_profiles",
    )
    op.drop_table("ai_provider_profiles")
