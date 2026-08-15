"""persist editable framework outline order

Revision ID: c3d5e7f9a1b2
Revises: b7d4f2a91c63
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d5e7f9a1b2"
down_revision: str | None = "b7d4f2a91c63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_map_versions") as batch_op:
        batch_op.add_column(
            sa.Column("outline_revision", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.create_check_constraint(
            "outline_revision_positive",
            "outline_revision >= 1",
        )
    with op.batch_alter_table("knowledge_node_versions") as batch_op:
        batch_op.add_column(
            sa.Column("outline_order", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.create_check_constraint(
            "outline_order_nonnegative",
            "outline_order >= 0",
        )

    bind = op.get_bind()
    version_ids = [
        row[0]
        for row in bind.execute(
            sa.text("SELECT id FROM knowledge_map_versions ORDER BY space_id, version_number")
        )
    ]
    for version_id in version_ids:
        rows = list(
            bind.execute(
                sa.text(
                    "SELECT id FROM knowledge_node_versions "
                    "WHERE map_version_id = :version_id "
                    "ORDER BY CASE WHEN node_type = 'MODULE' THEN 0 ELSE 1 END, created_at, id"
                ),
                {"version_id": version_id},
            )
        )
        for position, row in enumerate(rows):
            bind.execute(
                sa.text(
                    "UPDATE knowledge_node_versions SET outline_order = :position WHERE id = :id"
                ),
                {"position": position, "id": row[0]},
            )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_node_versions") as batch_op:
        batch_op.drop_constraint("outline_order_nonnegative", type_="check")
        batch_op.drop_column("outline_order")
    with op.batch_alter_table("knowledge_map_versions") as batch_op:
        batch_op.drop_constraint("outline_revision_positive", type_="check")
        batch_op.drop_column("outline_revision")
