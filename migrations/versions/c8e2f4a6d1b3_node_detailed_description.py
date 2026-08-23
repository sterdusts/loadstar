"""add detailed knowledge-node descriptions

Revision ID: c8e2f4a6d1b3
Revises: b7d1f4a8c2e6
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8e2f4a6d1b3"
down_revision: str | None = "b7d1f4a8c2e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table_name in ("knowledge_nodes", "knowledge_node_versions"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "detailed_description",
                    sa.Text(),
                    nullable=False,
                    server_default="",
                )
            )
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column("detailed_description", server_default=None)


def downgrade() -> None:
    for table_name in ("knowledge_node_versions", "knowledge_nodes"):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_column("detailed_description")
