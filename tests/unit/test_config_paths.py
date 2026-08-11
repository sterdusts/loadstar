"""Stable local-data path contracts."""

from pathlib import Path

import pytest

import learning_navigator.config as config_module
from learning_navigator.config import (
    Settings,
    ensure_runtime_root,
    persistent_storage_secret,
    resolve_database_url,
)
from learning_navigator.infrastructure.database.session import create_database_engine


def test_relative_sqlite_database_is_resolved_against_runtime_root(tmp_path: Path) -> None:
    resolved = resolve_database_url("sqlite:///./learning_navigator.db", base_dir=tmp_path)

    assert resolved == f"sqlite:///{(tmp_path / 'learning_navigator.db').as_posix()}"


def test_absolute_and_in_memory_sqlite_database_locations_are_preserved(tmp_path: Path) -> None:
    absolute = (tmp_path / "explicit.db").resolve()

    assert resolve_database_url(f"sqlite:///{absolute.as_posix()}", base_dir=tmp_path) == (
        f"sqlite:///{absolute.as_posix()}"
    )
    assert resolve_database_url("sqlite:///:memory:", base_dir=tmp_path) == "sqlite:///:memory:"
    assert resolve_database_url("sqlite://", base_dir=tmp_path) == "sqlite://"


def test_non_sqlite_database_url_is_not_rewritten(tmp_path: Path) -> None:
    value = "postgresql+psycopg://example.test/frame"

    assert resolve_database_url(value, base_dir=tmp_path) == value


def test_first_start_creates_missing_runtime_directory(tmp_path: Path) -> None:
    target = tmp_path / "not-created" / "Frame"

    assert ensure_runtime_root(target) == target
    assert target.is_dir()


def test_known_storage_secret_placeholders_are_never_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret_file = tmp_path / ".frame-storage-secret"
    monkeypatch.setattr(config_module, "STORAGE_SECRET_FILE", secret_file)
    configured = Settings(
        database_url="sqlite:///:memory:",
        storage_secret="replace-with-a-long-random-value",
    )

    secret = configured.storage_secret.get_secret_value()
    assert secret != "replace-with-a-long-random-value"
    assert len(secret) >= 32
    assert secret_file.read_text(encoding="utf-8") == secret
    assert persistent_storage_secret(secret_file) == secret
    assert Settings.model_fields["auto_create_schema"].default is False


def test_database_engine_never_logs_bound_personal_data() -> None:
    engine = create_database_engine("sqlite:///:memory:", echo=True)
    try:
        assert engine.hide_parameters is True
    finally:
        engine.dispose()
