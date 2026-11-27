"""Unit tests for PlainTextParser."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.rag.domain import BlockKind
from app.rag.parsing import EmptyDocumentError, InvalidDocumentError, PlainTextParser


def test_plain_text_utf8_and_turkish_characters(tmp_path: Path) -> None:
    text = (
        "# 1. Giriş\n\n"
        "Öğrenciler için hazırlanan bu metin ç, ğ, ı, İ, ö, ş, ü karakterlerini içerir.\n\n"
        "def topla(a, b):\n"
        "    return a + b\n"
    )
    txt_file = tmp_path / "notlar.txt"
    txt_file.write_text(text, encoding="utf-8")

    doc = PlainTextParser().parse(txt_file)
    assert doc.source_name == "notlar.txt"
    assert doc.file_type == "text/plain"
    assert doc.report.total_pages == 1
    assert doc.report.text_extracted_pages == (1,)
    assert doc.report.code_block_count == 1
    assert doc.pages[0].blocks[0].kind is BlockKind.HEADING
    assert doc.pages[0].blocks[0].text == "1. Giriş"
    assert doc.pages[0].blocks[1].kind is BlockKind.PARAGRAPH
    assert "ğ, ı, İ" in doc.pages[0].blocks[1].text
    assert doc.pages[0].blocks[2].kind is BlockKind.CODE
    assert doc.pages[0].blocks[2].language_hint == "python"
    assert "    return a + b" in doc.pages[0].blocks[2].text


def test_plain_text_supports_utf8_bom_and_crlf() -> None:
    raw = "\ufeffBaşlık\r\n\r\nBirinci satır.\r\nİkinci satır.\r\n".encode("utf-8")
    doc = PlainTextParser().parse(raw, source_name="bom.txt")
    assert not doc.full_text.startswith("\ufeff")
    assert "\r" not in doc.full_text
    assert "Başlık" in doc.full_text


def test_plain_text_fenced_code_block_preserves_indentation() -> None:
    raw = (
        "Açıklama paragrafı.\n\n"
        "```python\n"
        "for i in range(3):\n"
        "    if i % 2 == 0:\n"
        "        print(i)\n"
        "```\n"
    ).encode("utf-8")
    doc = PlainTextParser().parse(raw, source_name="fenced.txt")
    code_blocks = [b for b in doc.pages[0].blocks if b.kind is BlockKind.CODE]
    assert len(code_blocks) == 1
    assert code_blocks[0].language_hint == "python"
    assert "        print(i)" in code_blocks[0].text


def test_plain_text_rejects_empty_binary_and_invalid_utf8() -> None:
    parser = PlainTextParser()
    with pytest.raises(EmptyDocumentError) as exc_info:
        parser.parse(b"   \n\t  ")
    assert exc_info.value.report is not None
    assert exc_info.value.report.empty_pages == (1,)

    with pytest.raises(InvalidDocumentError):
        parser.parse(b"\xff\xfe\xfa\xfb")

    with pytest.raises(InvalidDocumentError):
        parser.parse(b"hello\x00binary")
