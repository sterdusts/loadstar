"""Migration-level checks for learning-path uniqueness invariants."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect


def _alembic(database: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["LN_DATABASE_URL"] = f"sqlite:///{database.as_posix()}"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_path_uniqueness_migration_round_trip_and_metadata_check(tmp_path: Path) -> None:
    database = tmp_path / "migration-round-trip.sqlite"
    upgraded = _alembic(database, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr

    engine = create_engine(f"sqlite:///{database.as_posix()}")
    constraints = {
        (item["name"], tuple(item["column_names"]))
        for item in inspect(engine).get_unique_constraints("learning_path_nodes")
    }
    assert (
        "uq_learning_path_nodes_path_id",
        ("path_id", "node_id"),
    ) in constraints
    assert (
        "uq_learning_path_nodes_path_sequence",
        ("path_id", "sequence_number"),
    ) in constraints

    metadata_check = _alembic(database, "check")
    assert metadata_check.returncode == 0, metadata_check.stderr
    assert "No new upgrade operations detected" in metadata_check.stdout

    downgraded = _alembic(database, "downgrade", "e91b4c7d2a60")
    assert downgraded.returncode == 0, downgraded.stderr
    upgraded_again = _alembic(database, "upgrade", "head")
    assert upgraded_again.returncode == 0, upgraded_again.stderr


def test_path_uniqueness_migration_refuses_ambiguous_existing_rows(tmp_path: Path) -> None:
    database = tmp_path / "migration-duplicates.sqlite"
    baseline = _alembic(database, "upgrade", "e91b4c7d2a60")
    assert baseline.returncode == 0, baseline.stderr
    legacy_constraints = {
        tuple(item["column_names"])
        for item in inspect(
            create_engine(f"sqlite:///{database.as_posix()}")
        ).get_unique_constraints("learning_path_nodes")
    }
    if ("path_id", "node_id") in legacy_constraints:
        second_node_id, second_sequence = "node-2", 0
    else:
        second_node_id, second_sequence = "node-1", 1

    with sqlite3.connect(database) as connection:
        values = (
            "path-1",
            "node-1",
            0,
            3,
            "reason",
            "[]",
            "[]",
            "[]",
            "AVAILABLE",
            1,
            "step-1",
            0,
            "LEARN",
            50,
            0,
            0,
            "MANUAL",
        )
        connection.execute(
            "INSERT INTO learning_path_nodes "
            "(path_id,node_id,sequence_number,required_mastery_level,recommendation_reason,"
            "satisfied_prerequisites,unmet_prerequisites,unlocks,computed_status,is_required,id,"
            "preferred_order,action_kind,priority,is_pinned,is_deferred,source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            values,
        )
        connection.execute(
            "INSERT INTO learning_path_nodes "
            "(path_id,node_id,sequence_number,required_mastery_level,recommendation_reason,"
            "satisfied_prerequisites,unmet_prerequisites,unlocks,computed_status,is_required,id,"
            "preferred_order,action_kind,priority,is_pinned,is_deferred,source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                values[0],
                second_node_id,
                second_sequence,
                *values[3:10],
                "step-2",
                *values[11:],
            ),
        )

    rejected = _alembic(database, "upgrade", "head")
    assert rejected.returncode != 0
    assert "duplicate nodes or positions exist" in (rejected.stdout + rejected.stderr)


def test_progress_clear_migration_moves_legacy_reset_scope_into_recovery(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy-progress-reset.sqlite"
    baseline = _alembic(database, "upgrade", "f5b8c3d6e9a2")
    assert baseline.returncode == 0, baseline.stderr

    with sqlite3.connect(database) as connection:
        check_in_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(node_progress_check_ins)")
        }
        shared = {
            "user_id": "user-legacy",
            "goal_id": "goal-legacy",
            "node_id": "node-legacy",
            "note": "legacy note",
            "duration_minutes": 60,
            "ai_evaluation": None,
            "ai_evaluated_at": None,
            "row_version": 1,
            "corrected_at": None,
            "created_at": "2026-08-14 10:00:00",
            "updated_at": "2026-08-14 10:00:00",
        }
        rows = [
            {
                **shared,
                "id": "check-in-positive",
                "checked_in_at": "2026-08-14 10:00:00",
                "check_in_date": "2026-08-14",
                "score": 7,
            },
            {
                **shared,
                "id": "check-in-zero-marker",
                "checked_in_at": "2026-08-15 10:00:00",
                "check_in_date": "2026-08-15",
                "score": 0,
                "note": None,
                "duration_minutes": 0,
                "created_at": "2026-08-15 10:00:00",
                "updated_at": "2026-08-15 10:00:00",
            },
        ]
        for row in rows:
            values = {key: value for key, value in row.items() if key in check_in_columns}
            columns = ",".join(values)
            placeholders = ",".join("?" for _ in values)
            connection.execute(
                f"INSERT INTO node_progress_check_ins ({columns}) VALUES ({placeholders})",
                tuple(values.values()),
            )

        attachment_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(progress_check_in_attachments)")
        }
        attachment = {
            "user_id": "user-legacy",
            "check_in_id": "check-in-positive",
            "original_name": "evidence.png",
            "media_type": "image/png",
            "size_bytes": 123,
            "sha256": "a" * 64,
            "storage_key": "legacy/evidence.png",
            "id": "attachment-legacy",
            "created_at": "2026-08-14 10:00:00",
            "updated_at": "2026-08-14 10:00:00",
        }
        attachment_values = {
            key: value for key, value in attachment.items() if key in attachment_columns
        }
        connection.execute(
            "INSERT INTO progress_check_in_attachments "
            f"({','.join(attachment_values)}) VALUES "
            f"({','.join('?' for _ in attachment_values)})",
            tuple(attachment_values.values()),
        )

    upgraded = _alembic(database, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM node_progress_check_ins").fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM progress_check_in_attachments"
        ).fetchone() == (0,)
        record_count, attachment_count, snapshot = connection.execute(
            "SELECT record_count, attachment_count, snapshot FROM progress_check_in_clear_batches"
        ).fetchone()
        assert record_count == 2
        assert attachment_count == 1
        payload = json.loads(snapshot)
        assert len(payload["check_ins"]) == 2
        assert all(item["check_in"]["score"] >= 1 for item in payload["check_ins"])
        reset_items = [item for item in payload["check_ins"] if item["legacy_reset_marker"]]
        assert len(reset_items) == 1
        assert reset_items[0]["check_in"]["id"] == "check-in-zero-marker"
        assert sum(len(item["attachments"]) for item in payload["check_ins"]) == 1

        create_sql = connection.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'node_progress_check_ins'"
        ).fetchone()[0]
        assert "score BETWEEN 1 AND 10" in create_sql
