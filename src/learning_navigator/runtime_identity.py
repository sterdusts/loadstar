"""Stable runtime identity used to distinguish current and stale local services."""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

PRODUCT_ID = "learning-navigator"
_SOURCE_DIRS = ("src/learning_navigator", "migrations")
_SOURCE_FILES = ("pyproject.toml", "uv.lock")


def source_checkout_root(package_file: Path | None = None) -> Path:
    """Locate the checkout that owns the imported package."""

    location = (package_file or Path(__file__)).resolve()
    for candidate in location.parents:
        if (candidate / "pyproject.toml").is_file() and (
            candidate / "src" / "learning_navigator"
        ).is_dir():
            return candidate
    return location.parent


def source_fingerprint(root: Path | None = None) -> str:
    """Hash runtime source and dependency metadata using a cross-platform manifest."""

    checkout = (root or source_checkout_root()).resolve()
    files: set[Path] = set()
    for relative_name in _SOURCE_FILES:
        candidate = checkout / relative_name
        if candidate.is_file():
            files.add(candidate)
    for relative_dir in _SOURCE_DIRS:
        directory = checkout / relative_dir
        if not directory.is_dir():
            continue
        files.update(
            candidate
            for candidate in directory.rglob("*")
            if candidate.is_file()
            and "__pycache__" not in candidate.parts
            and candidate.suffix != ".pyc"
        )

    manifest: list[str] = []
    for path in sorted(files, key=lambda item: item.relative_to(checkout).as_posix()):
        relative_path = path.relative_to(checkout).as_posix()
        file_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest.append(f"{relative_path}\0{file_digest}")
    return hashlib.sha256("\n".join(manifest).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class RuntimeIdentity:
    product_id: str
    source_fingerprint: str
    instance_token: str
    process_id: int


def build_runtime_identity() -> RuntimeIdentity:
    """Capture identity once at process startup so later file edits remain detectable."""

    return RuntimeIdentity(
        product_id=PRODUCT_ID,
        source_fingerprint=source_fingerprint(),
        instance_token=os.getenv("LN_LAUNCH_INSTANCE_TOKEN", "").strip() or uuid.uuid4().hex,
        process_id=os.getpid(),
    )
