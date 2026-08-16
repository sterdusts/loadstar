"""Durable, streaming storage for progress check-in attachments."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterable
from dataclasses import dataclass
from pathlib import Path

import anyio


@dataclass(frozen=True, slots=True)
class StoredAttachment:
    size_bytes: int
    sha256: str


class CheckInAttachmentStorage:
    """Store user uploads outside the database without buffering whole files."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, storage_key: str) -> Path:
        candidate = (self.root / storage_key).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError("Attachment storage key escapes the managed storage root")
        return candidate

    async def store(
        self,
        storage_key: str,
        chunks: AsyncIterable[bytes],
    ) -> StoredAttachment:
        target = self.path_for(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f"{target.suffix}.part")
        digest = hashlib.sha256()
        size_bytes = 0
        try:
            async with await anyio.open_file(temporary, "wb") as handle:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    digest.update(chunk)
                    size_bytes += len(chunk)
                    await handle.write(chunk)
            temporary.replace(target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            raise
        return StoredAttachment(size_bytes=size_bytes, sha256=digest.hexdigest())

    def delete(self, storage_key: str) -> None:
        target = self.path_for(storage_key)
        target.unlink(missing_ok=True)
        for parent in target.parents:
            if parent == self.root:
                break
            try:
                parent.rmdir()
            except OSError:
                break

    def delete_many(self, storage_keys: list[str]) -> None:
        for storage_key in storage_keys:
            self.delete(storage_key)
