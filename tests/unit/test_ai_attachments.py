"""Bounded extraction rules for files sent through the unified AI assistant."""

from __future__ import annotations

import zipfile
from pathlib import Path

from pypdf import PdfWriter

from learning_navigator.api.schemas.collaboration import ConversationSendRequest
from learning_navigator.infrastructure.storage.ai_attachments import (
    MAX_EXTRACTED_CHARS,
    MAX_PDF_INDEX_BYTES,
    index_ai_attachment,
)


def test_text_original_is_not_size_limited_but_provider_excerpt_is_bounded(tmp_path: Path) -> None:
    source = tmp_path / "large-notes.txt"
    source.write_text("数学结构与学习路径\n" * 20_000, encoding="utf-8")

    indexed = index_ai_attachment(source, source.name, "text/plain")

    assert source.stat().st_size > MAX_EXTRACTED_CHARS
    assert indexed.kind == "text"
    assert indexed.status == "PARTIAL"
    assert len(indexed.text) == MAX_EXTRACTED_CHARS
    assert indexed.metadata["truncated"] is True


def test_zip_is_read_in_place_and_skips_unsafe_members(tmp_path: Path) -> None:
    source = tmp_path / "materials.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("课程/目标.md", "建立统计学习框架")
        archive.writestr("课程/练习.txt", "完成一个回归分析项目")
        archive.writestr("../escape.txt", "不得写出压缩包")

    indexed = index_ai_attachment(source, source.name, "application/zip")

    assert indexed.kind == "archive"
    assert indexed.status == "PARTIAL"
    assert "建立统计学习框架" in indexed.text
    assert "完成一个回归分析项目" in indexed.text
    assert indexed.metadata["skipped_unsafe"] == 1
    assert not (tmp_path / "escape.txt").exists()


def test_corrupt_archive_is_kept_locally_with_an_indexing_error(tmp_path: Path) -> None:
    source = tmp_path / "broken.zip"
    source.write_bytes(b"not-a-zip")

    indexed = index_ai_attachment(source, source.name, "application/zip")

    assert indexed.kind == "unknown"
    assert indexed.status == "ERROR"
    assert indexed.metadata["reason"] == "BadZipFile"


def test_images_and_pdf_are_classified_without_mutating_the_original(tmp_path: Path) -> None:
    image = tmp_path / "diagram.png"
    image_bytes = b"\x89PNG\r\n\x1a\nlocal-image-evidence"
    image.write_bytes(image_bytes)
    image_index = index_ai_attachment(image, image.name, "image/png")

    pdf = tmp_path / "outline.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with pdf.open("wb") as handle:
        writer.write(handle)
    pdf_index = index_ai_attachment(pdf, pdf.name, "application/pdf")

    assert image.read_bytes() == image_bytes
    assert image_index.kind == "image"
    assert image_index.metadata["vision_candidate"] is True
    assert pdf_index.kind == "document"
    assert pdf_index.status == "INDEXED"
    assert pdf_index.metadata["pages"] == 1


def test_office_zip_bomb_is_saved_but_not_expanded_for_indexing(tmp_path: Path) -> None:
    source = tmp_path / "compressed-notes.docx"
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", "<w:t>数学</w:t>" * 500_000)

    indexed = index_ai_attachment(
        source,
        source.name,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert indexed.kind == "document"
    assert indexed.status == "PARTIAL"
    assert indexed.text == ""
    assert indexed.metadata["skipped_large"] == 1
    assert indexed.metadata["bytes_inspected"] == 0


def test_oversized_pdf_is_kept_without_unbounded_local_indexing(tmp_path: Path) -> None:
    source = tmp_path / "huge-reference.pdf"
    with source.open("wb") as handle:
        handle.seek(MAX_PDF_INDEX_BYTES)
        handle.write(b"0")

    indexed = index_ai_attachment(source, source.name, "application/pdf")

    assert source.stat().st_size > MAX_PDF_INDEX_BYTES
    assert indexed.kind == "document"
    assert indexed.status == "PARTIAL"
    assert indexed.metadata["reason"] == "pdf_too_large_for_local_index"


def test_message_schema_accepts_attachment_only_and_large_batches() -> None:
    attachment_ids = [f"attachment-{index}" for index in range(1_000)]

    payload = ConversationSendRequest(content="", attachment_ids=attachment_ids)

    assert payload.attachment_ids == attachment_ids
