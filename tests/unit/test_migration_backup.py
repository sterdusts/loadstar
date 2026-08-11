"""Migration backup safety contracts."""

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import backup_before_migration as backup_module


def _database_url(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"


def test_pending_migration_creates_verified_sqlite_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "frame.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
        connection.execute("INSERT INTO sample VALUES ('preserved')")

    monkeypatch.setattr(
        backup_module,
        "get_settings",
        lambda: SimpleNamespace(database_url=_database_url(database)),
    )
    monkeypatch.setattr(backup_module, "_current_revision", lambda _url: "old")
    monkeypatch.setattr(backup_module, "_migration_head", lambda: "head")

    backup = backup_module.backup_before_migration()

    assert backup is not None
    assert backup.parent == tmp_path / "backups"
    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT value FROM sample").fetchone() == ("preserved",)


def test_current_schema_does_not_create_redundant_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "frame.db"
    database.touch()
    monkeypatch.setattr(
        backup_module,
        "get_settings",
        lambda: SimpleNamespace(database_url=_database_url(database)),
    )
    monkeypatch.setattr(backup_module, "_current_revision", lambda _url: "head")
    monkeypatch.setattr(backup_module, "_migration_head", lambda: "head")

    assert backup_module.backup_before_migration() is None
    assert not (tmp_path / "backups").exists()
