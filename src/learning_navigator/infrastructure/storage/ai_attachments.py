"""Safe, bounded extraction for files attached to AI conversations."""

from __future__ import annotations

import gzip
import html
import json
import mimetypes
import re
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_EXTRACTED_CHARS = 120_000
MAX_ARCHIVE_ENTRIES = 500
MAX_ARCHIVE_READ_BYTES = 32 * 1024 * 1024
MAX_MEMBER_BYTES = 8 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200
MAX_PDF_INDEX_BYTES = 128 * 1024 * 1024
MAX_PDF_PAGES = 200

_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".csv",
    ".tsv",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".log",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".go",
    ".rs",
    ".sql",
    ".sh",
    ".ps1",
}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_ARCHIVE_EXTENSIONS = {".zip", ".tar", ".tgz", ".gz", ".tar.gz"}


@dataclass(frozen=True, slots=True)
class IndexedAIFile:
    kind: str
    status: str
    text: str
    metadata: dict[str, Any]


def _safe_member_name(value: str) -> str | None:
    normalized = value.replace("\\", "/")
    candidate = PurePosixPath(normalized)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    cleaned = "/".join(part for part in candidate.parts if part not in {"", "."})
    return cleaned or None


def _decode_text(payload: bytes) -> str:
    if b"\x00" in payload[:4096]:
        return ""
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "utf-16"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")


def _clean_xml(payload: bytes) -> str:
    source = _decode_text(payload)
    source = re.sub(r"<w:tab[^>]*/>", "\t", source)
    source = re.sub(r"</w:p>|</a:p>|</row>", "\n", source)
    source = re.sub(r"<[^>]+>", " ", source)
    return " ".join(html.unescape(source).split())


def _truncate(value: str) -> tuple[str, bool]:
    if len(value) <= MAX_EXTRACTED_CHARS:
        return value, False
    return value[:MAX_EXTRACTED_CHARS], True


def _office_text(path: Path, suffix: str) -> IndexedAIFile:
    prefixes = {
        ".docx": ("word/",),
        ".pptx": ("ppt/slides/", "ppt/notesSlides/"),
        ".xlsx": ("xl/sharedStrings.xml", "xl/worksheets/"),
    }[suffix]
    parts: list[str] = []
    inspected = 0
    total_read = 0
    skipped_large = 0
    truncated = False
    with zipfile.ZipFile(path) as archive:
        for position, info in enumerate(archive.infolist()):
            if position >= MAX_ARCHIVE_ENTRIES:
                truncated = True
                break
            if not any(info.filename.startswith(prefix) for prefix in prefixes):
                continue
            compressed = max(info.compress_size, 1)
            if (
                info.file_size > MAX_MEMBER_BYTES
                or info.file_size / compressed > MAX_COMPRESSION_RATIO
                or total_read + info.file_size > MAX_ARCHIVE_READ_BYTES
            ):
                skipped_large += 1
                continue
            inspected += 1
            payload = archive.read(info)
            total_read += len(payload)
            parts.append(_clean_xml(payload))
            if sum(map(len, parts)) >= MAX_EXTRACTED_CHARS:
                truncated = True
                break
    text, text_truncated = _truncate("\n".join(part for part in parts if part))
    truncated = truncated or text_truncated or bool(skipped_large)
    return IndexedAIFile(
        kind="document",
        status="PARTIAL" if truncated else "INDEXED",
        text=text,
        metadata={
            "format": suffix.removeprefix("."),
            "parts_inspected": inspected,
            "bytes_inspected": total_read,
            "skipped_large": skipped_large,
            "truncated": truncated,
        },
    )


def _zip_text(path: Path) -> IndexedAIFile:
    manifest: list[dict[str, Any]] = []
    parts: list[str] = []
    total_read = 0
    skipped_unsafe = 0
    skipped_large = 0
    truncated = False
    with zipfile.ZipFile(path) as archive:
        for position, info in enumerate(archive.infolist()):
            if position >= MAX_ARCHIVE_ENTRIES:
                truncated = True
                break
            name = _safe_member_name(info.filename)
            if name is None:
                skipped_unsafe += 1
                continue
            manifest.append({"name": name, "size_bytes": info.file_size})
            if info.is_dir() or Path(name).suffix.lower() not in _TEXT_EXTENSIONS:
                continue
            compressed = max(info.compress_size, 1)
            if (
                info.file_size > MAX_MEMBER_BYTES
                or info.file_size / compressed > MAX_COMPRESSION_RATIO
                or total_read + info.file_size > MAX_ARCHIVE_READ_BYTES
            ):
                skipped_large += 1
                continue
            payload = archive.read(info)
            total_read += len(payload)
            text = _decode_text(payload)
            if text:
                parts.append(f"\n--- {name} ---\n{text}")
            if sum(map(len, parts)) >= MAX_EXTRACTED_CHARS:
                truncated = True
                break
    text, text_truncated = _truncate("".join(parts).strip())
    truncated = truncated or text_truncated
    return IndexedAIFile(
        kind="archive",
        status="PARTIAL" if truncated or skipped_large or skipped_unsafe else "INDEXED",
        text=text,
        metadata={
            "format": "zip",
            "entries": manifest,
            "entry_count": len(manifest),
            "bytes_inspected": total_read,
            "skipped_unsafe": skipped_unsafe,
            "skipped_large": skipped_large,
            "truncated": truncated,
        },
    )


def _tar_text(path: Path) -> IndexedAIFile:
    manifest: list[dict[str, Any]] = []
    parts: list[str] = []
    total_read = 0
    skipped_unsafe = 0
    skipped_large = 0
    truncated = False
    with tarfile.open(path, mode="r:*") as archive:
        for position, member in enumerate(archive):
            if position >= MAX_ARCHIVE_ENTRIES:
                truncated = True
                break
            name = _safe_member_name(member.name)
            if name is None:
                skipped_unsafe += 1
                continue
            manifest.append({"name": name, "size_bytes": member.size})
            if not member.isfile() or Path(name).suffix.lower() not in _TEXT_EXTENSIONS:
                continue
            if member.size > MAX_MEMBER_BYTES or total_read + member.size > MAX_ARCHIVE_READ_BYTES:
                skipped_large += 1
                continue
            handle = archive.extractfile(member)
            if handle is None:
                continue
            payload = handle.read(MAX_MEMBER_BYTES + 1)
            total_read += len(payload)
            text = _decode_text(payload)
            if text:
                parts.append(f"\n--- {name} ---\n{text}")
            if sum(map(len, parts)) >= MAX_EXTRACTED_CHARS:
                truncated = True
                break
    text, text_truncated = _truncate("".join(parts).strip())
    truncated = truncated or text_truncated
    return IndexedAIFile(
        kind="archive",
        status="PARTIAL" if truncated or skipped_large or skipped_unsafe else "INDEXED",
        text=text,
        metadata={
            "format": "tar",
            "entries": manifest,
            "entry_count": len(manifest),
            "bytes_inspected": total_read,
            "skipped_unsafe": skipped_unsafe,
            "skipped_large": skipped_large,
            "truncated": truncated,
        },
    )


def index_ai_attachment(path: Path, original_name: str, media_type: str | None) -> IndexedAIFile:
    """Index a local upload without executing it or extracting archive members to disk."""

    lower_name = original_name.lower()
    suffix = ".tar.gz" if lower_name.endswith(".tar.gz") else Path(lower_name).suffix
    guessed = media_type or mimetypes.guess_type(original_name)[0] or "application/octet-stream"
    try:
        if suffix in _IMAGE_EXTENSIONS or guessed.startswith("image/"):
            return IndexedAIFile(
                kind="image",
                status="INDEXED",
                text="",
                metadata={"format": suffix.removeprefix("."), "vision_candidate": True},
            )
        if suffix in _TEXT_EXTENSIONS or guessed.startswith("text/"):
            with path.open("rb") as handle:
                payload = handle.read(MAX_ARCHIVE_READ_BYTES + 1)
            text, truncated = _truncate(_decode_text(payload))
            truncated = truncated or len(payload) > MAX_ARCHIVE_READ_BYTES
            return IndexedAIFile(
                kind="text",
                status="PARTIAL" if truncated else "INDEXED",
                text=text,
                metadata={"format": suffix.removeprefix("."), "truncated": truncated},
            )
        if suffix in {".docx", ".pptx", ".xlsx"}:
            return _office_text(path, suffix)
        if suffix == ".zip":
            return _zip_text(path)
        if suffix in {".tar", ".tgz", ".tar.gz"}:
            return _tar_text(path)
        if suffix == ".gz":
            with gzip.open(path, "rb") as handle:
                payload = handle.read(MAX_ARCHIVE_READ_BYTES + 1)
            text, truncated = _truncate(_decode_text(payload))
            truncated = truncated or len(payload) > MAX_ARCHIVE_READ_BYTES
            return IndexedAIFile(
                kind="archive",
                status="PARTIAL" if truncated else "INDEXED",
                text=text,
                metadata={"format": "gzip", "truncated": truncated},
            )
        if suffix == ".pdf":
            source_size = path.stat().st_size
            if source_size > MAX_PDF_INDEX_BYTES:
                return IndexedAIFile(
                    kind="document",
                    status="PARTIAL",
                    text="",
                    metadata={
                        "format": "pdf",
                        "reason": "pdf_too_large_for_local_index",
                        "size_bytes": source_size,
                        "truncated": True,
                    },
                )
            reader = PdfReader(str(path))
            parts: list[str] = []
            total_chars = 0
            pages_inspected = 0
            for page in reader.pages[:MAX_PDF_PAGES]:
                page_text = page.extract_text() or ""
                parts.append(page_text)
                total_chars += len(page_text)
                pages_inspected += 1
                if total_chars >= MAX_EXTRACTED_CHARS:
                    break
            text, text_truncated = _truncate("\n".join(parts))
            truncated = (
                text_truncated
                or pages_inspected < len(reader.pages)
                or total_chars >= MAX_EXTRACTED_CHARS
            )
            return IndexedAIFile(
                kind="document",
                status="PARTIAL" if truncated else "INDEXED",
                text=text,
                metadata={
                    "format": "pdf",
                    "pages": len(reader.pages),
                    "pages_inspected": pages_inspected,
                    "truncated": truncated,
                },
            )
    except (
        OSError,
        ValueError,
        zipfile.BadZipFile,
        tarfile.TarError,
        EOFError,
        json.JSONDecodeError,
        PdfReadError,
    ) as exc:
        return IndexedAIFile(
            kind="unknown",
            status="ERROR",
            text="",
            metadata={"reason": type(exc).__name__},
        )
    return IndexedAIFile(
        kind="unknown",
        status="UNSUPPORTED",
        text="",
        metadata={"format": suffix.removeprefix(".") or "unknown"},
    )
