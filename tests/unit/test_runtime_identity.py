from __future__ import annotations

from pathlib import Path

from learning_navigator.runtime_identity import (
    PRODUCT_ID,
    build_runtime_identity,
    source_fingerprint,
)


def _write_source(root: Path, content: str) -> None:
    package = root / "src" / "learning_navigator"
    package.mkdir(parents=True, exist_ok=True)
    (package / "sample.py").write_text(content, encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='sample'\n", encoding="utf-8")


def test_source_fingerprint_is_stable_and_changes_with_runtime_source(tmp_path: Path) -> None:
    _write_source(tmp_path, "VALUE = 1\n")
    first = source_fingerprint(tmp_path)
    assert first == source_fingerprint(tmp_path)

    _write_source(tmp_path, "VALUE = 2\n")
    assert source_fingerprint(tmp_path) != first


def test_runtime_identity_uses_launcher_token(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("LN_LAUNCH_INSTANCE_TOKEN", "launcher-owned-token")
    identity = build_runtime_identity()
    assert identity.product_id == PRODUCT_ID
    assert identity.instance_token == "launcher-owned-token"
    assert identity.process_id > 0
