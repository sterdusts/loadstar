"""Create a verified SQLite backup only when a schema migration is pending."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from learning_navigator.config import get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _sqlite_path(database_url: str) -> Path | None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite") or url.database in {None, "", ":memory:"}:
        return None
    if str(url.database).startswith("file:"):
        return None
    return Path(str(url.database)).resolve()


def _migration_head() -> str:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise RuntimeError("Alembic has no migration head")
    return head


def _current_revision(database_url: str) -> str | None:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def _assert_integrity(connection: sqlite3.Connection, *, label: str) -> None:
    result = connection.execute("PRAGMA integrity_check").fetchone()
    if result is None or result[0] != "ok":
        raise RuntimeError(f"{label} failed SQLite integrity_check")


def backup_before_migration() -> Path | None:
    settings = get_settings()
    database_path = _sqlite_path(settings.database_url)
    if database_path is None:
        print("Migration backup skipped: the configured database is not a file-backed SQLite DB.")
        return None
    if not database_path.exists():
        print("Migration backup skipped: the database will be created by Alembic.")
        return None
    current = _current_revision(settings.database_url)
    head = _migration_head()
    if current == head:
        print(f"Migration backup skipped: database is already at {head}.")
        return None

    backup_dir = database_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"{database_path.stem}.pre-migration.{timestamp}.db"
    with sqlite3.connect(database_path) as source, sqlite3.connect(backup_path) as target:
        _assert_integrity(source, label="Source database")
        source.backup(target)
        _assert_integrity(target, label="Migration backup")
    print(f"Verified migration backup: {backup_path}")
    return backup_path


if __name__ == "__main__":
    backup_before_migration()
