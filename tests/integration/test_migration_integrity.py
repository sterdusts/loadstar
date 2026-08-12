"""Migration-level checks for learning-path uniqueness invariants."""

from __future__ import annotations

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
