"""add recoverable progress clearing

Revision ID: a6c9e2f4b7d1
Revises: f5b8c3d6e9a2
Create Date: 2026-08-16
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "a6c9e2f4b7d1"
down_revision: str | None = "f5b8c3d6e9a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def upgrade() -> None:
    op.create_table(
        "progress_check_in_clear_batches",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("goal_id", sa.String(), nullable=False),
        sa.Column("node_id", sa.String(), nullable=False),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("attachment_count", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attachment_count >= 0", name="attachment_count_nonnegative"),
        sa.CheckConstraint("record_count >= 1", name="record_count_positive"),
        sa.ForeignKeyConstraint(["goal_id"], ["learning_goals.id"]),
        sa.ForeignKeyConstraint(["node_id"], ["knowledge_nodes.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_progress_check_in_clear_batches_goal_id",
        "progress_check_in_clear_batches",
        ["goal_id"],
    )
    op.create_index(
        "ix_progress_check_in_clear_batches_node_id",
        "progress_check_in_clear_batches",
        ["node_id"],
    )
    op.create_index(
        "ix_progress_check_in_clear_batches_user_id",
        "progress_check_in_clear_batches",
        ["user_id"],
    )
    op.create_index(
        "ix_progress_check_in_clear_batches_scope_time",
        "progress_check_in_clear_batches",
        ["user_id", "goal_id", "node_id", "cleared_at"],
    )

    connection = op.get_bind()
    check_ins = sa.table(
        "node_progress_check_ins",
        sa.column("user_id", sa.String()),
        sa.column("goal_id", sa.String()),
        sa.column("node_id", sa.String()),
        sa.column("checked_in_at", sa.DateTime(timezone=True)),
        sa.column("check_in_date", sa.Date()),
        sa.column("score", sa.Integer()),
        sa.column("note", sa.Text()),
        sa.column("duration_minutes", sa.Integer()),
        sa.column("ai_evaluation", sa.JSON()),
        sa.column("ai_evaluated_at", sa.DateTime(timezone=True)),
        sa.column("row_version", sa.Integer()),
        sa.column("corrected_at", sa.DateTime(timezone=True)),
        sa.column("id", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    attachments = sa.table(
        "progress_check_in_attachments",
        sa.column("user_id", sa.String()),
        sa.column("check_in_id", sa.String()),
        sa.column("original_name", sa.String()),
        sa.column("media_type", sa.String()),
        sa.column("size_bytes", sa.BigInteger()),
        sa.column("sha256", sa.String()),
        sa.column("storage_key", sa.String()),
        sa.column("id", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    clear_batches = sa.table(
        "progress_check_in_clear_batches",
        sa.column("user_id", sa.String()),
        sa.column("goal_id", sa.String()),
        sa.column("node_id", sa.String()),
        sa.column("cleared_at", sa.DateTime(timezone=True)),
        sa.column("restored_at", sa.DateTime(timezone=True)),
        sa.column("record_count", sa.Integer()),
        sa.column("attachment_count", sa.Integer()),
        sa.column("snapshot", sa.JSON()),
        sa.column("id", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in connection.execute(sa.select(check_ins)).mappings():
        payload = dict(row)
        key = (
            str(payload["user_id"]),
            str(payload["goal_id"]),
            str(payload["node_id"]),
        )
        grouped.setdefault(key, []).append(payload)
    migrated_at = datetime.now(UTC)
    for (user_id, goal_id, node_id), rows in grouped.items():
        latest = max(
            rows,
            key=lambda item: (
                str(item.get("check_in_date") or ""),
                str(item.get("checked_in_at") or ""),
                str(item.get("id") or ""),
            ),
        )
        if int(latest.get("score") or 0) != 0:
            continue
        check_in_ids = [str(row["id"]) for row in rows]
        raw_attachments = [
            dict(row)
            for row in connection.execute(
                sa.select(attachments).where(attachments.c.check_in_id.in_(check_in_ids))
            ).mappings()
        ]
        attachments_by_check_in: dict[str, list[dict[str, Any]]] = {}
        for attachment in raw_attachments:
            attachments_by_check_in.setdefault(str(attachment["check_in_id"]), []).append(
                attachment
            )
        snapshot_items = []
        for row in rows:
            check_in_payload = _json_value(row)
            legacy_reset_marker = int(row.get("score") or 0) == 0
            if legacy_reset_marker:
                check_in_payload["score"] = 1
            snapshot_items.append(
                {
                    "check_in": check_in_payload,
                    "attachments": _json_value(attachments_by_check_in.get(str(row["id"]), [])),
                    "legacy_reset_marker": legacy_reset_marker,
                }
            )
        connection.execute(
            clear_batches.insert().values(
                user_id=user_id,
                goal_id=goal_id,
                node_id=node_id,
                cleared_at=migrated_at,
                restored_at=None,
                record_count=len(rows),
                attachment_count=len(raw_attachments),
                snapshot={"version": 1, "check_ins": snapshot_items},
                id=str(uuid4()),
                created_at=migrated_at,
                updated_at=migrated_at,
            )
        )
        if raw_attachments:
            connection.execute(
                attachments.delete().where(
                    attachments.c.id.in_([str(row["id"]) for row in raw_attachments])
                )
            )
        connection.execute(check_ins.delete().where(check_ins.c.id.in_(check_in_ids)))

    with op.batch_alter_table("node_progress_check_ins") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_node_progress_check_ins_score_range"),
            type_="check",
        )
        batch_op.create_check_constraint("score_range", "score BETWEEN 1 AND 10")


def downgrade() -> None:
    connection = op.get_bind()
    active_batches = connection.scalar(
        sa.text("SELECT COUNT(*) FROM progress_check_in_clear_batches WHERE restored_at IS NULL")
    )
    if active_batches:
        raise RuntimeError("Restore or permanently discard cleared progress before downgrading")
    with op.batch_alter_table("node_progress_check_ins") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_node_progress_check_ins_score_range"),
            type_="check",
        )
        batch_op.create_check_constraint("score_range", "score BETWEEN 0 AND 10")
    op.drop_index(
        "ix_progress_check_in_clear_batches_scope_time",
        table_name="progress_check_in_clear_batches",
    )
    op.drop_index(
        "ix_progress_check_in_clear_batches_user_id",
        table_name="progress_check_in_clear_batches",
    )
    op.drop_index(
        "ix_progress_check_in_clear_batches_node_id",
        table_name="progress_check_in_clear_batches",
    )
    op.drop_index(
        "ix_progress_check_in_clear_batches_goal_id",
        table_name="progress_check_in_clear_batches",
    )
    op.drop_table("progress_check_in_clear_batches")
