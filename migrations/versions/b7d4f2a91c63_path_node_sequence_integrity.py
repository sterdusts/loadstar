"""enforce one sequence position per learning path

Revision ID: b7d4f2a91c63
Revises: e91b4c7d2a60
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7d4f2a91c63"
down_revision: str | None = "e91b4c7d2a60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    duplicate_node = bind.execute(
        sa.text(
            "SELECT 1 FROM learning_path_nodes "
            "GROUP BY path_id, node_id HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    duplicate_sequence = bind.execute(
        sa.text(
            "SELECT 1 FROM learning_path_nodes "
            "GROUP BY path_id, sequence_number HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate_node is not None or duplicate_sequence is not None:
        raise RuntimeError(
            "Cannot enforce learning path integrity: duplicate nodes or positions exist"
        )

    with op.batch_alter_table("learning_path_nodes") as batch_op:
        # The initial migration assigned this same generated name to two different
        # constraints. SQLite retained only one of them, so replace the ambiguous
        # survivor and create both intended invariants with stable, distinct names.
        batch_op.drop_constraint(
            "uq_learning_path_nodes_path_id",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_learning_path_nodes_path_id",
            ["path_id", "node_id"],
        )
        batch_op.create_unique_constraint(
            "uq_learning_path_nodes_path_sequence",
            ["path_id", "sequence_number"],
        )


def downgrade() -> None:
    with op.batch_alter_table("learning_path_nodes") as batch_op:
        batch_op.drop_constraint(
            "uq_learning_path_nodes_path_sequence",
            type_="unique",
        )
