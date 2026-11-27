"""Unit tests for PdfDocumentParser using synthetic PDF fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.rag.domain import BlockKind
from app.rag.parsing import (
    EmptyDocumentError,
    EncryptedDocumentError,
    InvalidDocumentError,
    PdfDocumentParser,
)
from tests.rag.pdf_factory import PageSpec, TextItem, build_pdf


def test_normal_pdf_text_and_heading(tmp_path: Path) -> None:
    pdf_bytes = build_pdf(
        [
            PageSpec(
                items=(
                    TextItem("1. Veri Yapilari Giris", x=72, y=720, size=16, font="bold"),
                    TextItem("Bagli listeler dinamik bellek kullanir.", x=72, y=690),
                    TextItem("Her dugum bir sonraki dugumu isaret eder.", x=72, y=674),
                )
            )
        ]
    )
    pdf_file = tmp_path / "normal.pdf"
    pdf_file.write_bytes(pdf_bytes)

    doc = PdfDocumentParser().parse(pdf_file)
    assert doc.source_name == "normal.pdf"
    assert doc.file_type == "application/pdf"
    assert doc.report.total_pages == 1
    assert doc.report.text_extracted_pages == (1,)
    assert doc.report.empty_pages == ()
    assert doc.pages[0].blocks[0].kind is BlockKind.HEADING
    assert "Veri Yapilari" in doc.pages[0].blocks[0].text
    assert doc.pages[0].blocks[1].kind is BlockKind.PARAGRAPH
    assert "dinamik bellek" in doc.full_text


def test_multipage_pdf_preserves_page_numbers() -> None:
    pdf_bytes = build_pdf(
        [
            PageSpec(items=(TextItem("Birinci sayfa metni.", x=72, y=700),)),
            PageSpec(items=(TextItem("Ikinci sayfa metni.", x=72, y=700),)),
            PageSpec(items=(TextItem("Ucuncu sayfa metni.", x=72, y=700),)),
        ]
    )
    doc = PdfDocumentParser().parse(pdf_bytes, source_name="multi.pdf")
    assert [p.page_number for p in doc.pages] == [1, 2, 3]
    assert doc.report.text_extracted_pages == (1, 2, 3)
    assert "Birinci" in doc.pages[0].text
    assert "Ikinci" in doc.pages[1].text
    assert "Ucuncu" in doc.pages[2].text


def test_turkish_characters_are_preserved() -> None:
    sample = "Öğrenciler için ağaç, düğüm, ışık, Şekil, Çıktı ve Üst düzey örnek."
    pdf_bytes = build_pdf([PageSpec(items=(TextItem(sample, x=72, y=700),))])

    doc = PdfDocumentParser().parse(pdf_bytes, source_name="turkce.pdf")
    extracted = doc.full_text
    for expected in ("Öğrenciler", "ağaç", "düğüm", "ışık", "Şekil", "Çıktı", "Üst"):
        assert expected in extracted


def test_c_pointer_and_printf_code_block_is_detected_and_preserved() -> None:
    pdf_bytes = build_pdf(
        [
            PageSpec(
                items=(
                    TextItem("C Pointer Ornegi", x=72, y=730, size=15, font="bold"),
                    TextItem("Asagidaki kod adresi yazdirir:", x=72, y=704),
                    TextItem("#include <stdio.h>", x=72, y=670, size=10, font="code"),
                    TextItem("int main(void) {", x=72, y=656, size=10, font="code"),
                    TextItem("int x = 42;", x=96, y=642, size=10, font="code"),
                    TextItem("int *p = &x;", x=96, y=628, size=10, font="code"),
                    TextItem('printf("%d\\n", *p);', x=96, y=614, size=10, font="code"),
                    TextItem("return 0;", x=96, y=600, size=10, font="code"),
                    TextItem("}", x=72, y=586, size=10, font="code"),
                )
            )
        ]
    )
    doc = PdfDocumentParser().parse(pdf_bytes, source_name="pointers.pdf")
    code_blocks = [b for b in doc.pages[0].blocks if b.kind is BlockKind.CODE]
    assert len(code_blocks) == 1
    code = code_blocks[0]
    assert code.language_hint == "c"
    assert doc.report.code_block_count == 1
    assert "#include <stdio.h>" in code.text
    assert 'printf("%d\\n", *p);' in code.text
    # Indented inner lines must preserve leading spaces relative to outer lines.
    indented_line = [ln for ln in code.text.splitlines() if "printf" in ln][0]
    assert indented_line.startswith("    ")


def test_python_code_indentation_is_preserved() -> None:
    pdf_bytes = build_pdf(
        [
            PageSpec(
                items=(
                    TextItem("Python Fonksiyonu", x=72, y=730, size=15, font="bold"),
                    TextItem("def factorial(n):", x=72, y=690, size=10, font="code"),
                    TextItem("if n <= 1:", x=96, y=676, size=10, font="code"),
                    TextItem("return 1", x=120, y=662, size=10, font="code"),
                    TextItem("return n * factorial(n - 1)", x=96, y=648, size=10, font="code"),
                )
            )
        ]
    )
    doc = PdfDocumentParser().parse(pdf_bytes, source_name="python.pdf")
    code_blocks = [b for b in doc.pages[0].blocks if b.kind is BlockKind.CODE]
    assert len(code_blocks) == 1
    assert code_blocks[0].language_hint == "python"
    lines = code_blocks[0].text.splitlines()
    assert lines[0] == "def factorial(n):"
    assert lines[1].startswith("    if n <= 1:")
    assert lines[2].startswith("        return 1")
    assert lines[3].startswith("    return n * factorial(n - 1)")


def test_two_column_pdf_reads_left_column_before_right_column() -> None:
    pdf_bytes = build_pdf(
        [
            PageSpec(
                items=(
                    TextItem("Sol sutun birinci satir metni.", x=50, y=700),
                    TextItem("Sol sutun ikinci satir metni.", x=50, y=684),
                    TextItem("Sag sutun birinci satir metni.", x=340, y=700),
                    TextItem("Sag sutun ikinci satir metni.", x=340, y=684),
                )
            )
        ]
    )
    doc = PdfDocumentParser().parse(pdf_bytes, source_name="twocol.pdf")
    text = doc.full_text
    assert text.index("Sol sutun ikinci") < text.index("Sag sutun birinci")


def test_empty_page_is_reported_while_other_pages_succeed() -> None:
    pdf_bytes = build_pdf(
        [
            PageSpec(items=(TextItem("Sayfa 1 icerigi burada.", x=72, y=700),)),
            PageSpec(items=(), image_count=0),
            PageSpec(items=(TextItem("Sayfa 3 icerigi burada.", x=72, y=700),)),
        ]
    )
    doc = PdfDocumentParser().parse(pdf_bytes, source_name="with_empty.pdf")
    assert doc.report.total_pages == 3
    assert doc.report.text_extracted_pages == (1, 3)
    assert doc.report.empty_pages == (2,)
    assert doc.pages[1].is_empty is True


def test_completely_empty_pdf_raises_empty_document_error_with_report() -> None:
    pdf_bytes = build_pdf([PageSpec(items=(), image_count=0)])
    with pytest.raises(EmptyDocumentError) as exc_info:
        PdfDocumentParser().parse(pdf_bytes, source_name="empty.pdf")
    assert exc_info.value.report is not None
    assert exc_info.value.report.empty_pages == (1,)
    assert exc_info.value.report.text_extracted_pages == ()


def test_image_bearing_page_and_suspected_scanned_page_are_reported() -> None:
    pdf_bytes = build_pdf(
        [
            # Page 1: real text + diagram image -> NOT scanned, but image reported
            PageSpec(
                items=(
                    TextItem(
                        "Bu sayfada metin ve bir diyagram gorseli birlikte bulunur.",
                        x=72,
                        y=700,
                    ),
                ),
                image_count=1,
            ),
            # Page 2: image only, no text -> suspected scanned page
            PageSpec(items=(), image_count=1),
        ]
    )
    doc = PdfDocumentParser().parse(pdf_bytes, source_name="diagrams.pdf")
    report = doc.report
    assert report.total_pages == 2
    assert report.text_extracted_pages == (1,)
    assert report.image_pages == (1, 2)
    assert report.suspected_scanned_pages == (2,)
    assert doc.pages[0].suspected_scanned is False
    assert doc.pages[1].suspected_scanned is True
    assert len(report.unprocessed_items) == 2
    assert any("kesin OCR sonucu degildir" in w for w in report.warnings)
    as_dict = report.to_dict()
    assert as_dict["suspected_scanned_pages"] == [2]
    assert as_dict["image_pages"] == [1, 2]


def test_all_scanned_pdf_raises_empty_document_error_with_scanned_report() -> None:
    pdf_bytes = build_pdf([PageSpec(items=(), image_count=1)])
    with pytest.raises(EmptyDocumentError) as exc_info:
        PdfDocumentParser().parse(pdf_bytes, source_name="scanned_only.pdf")
    report = exc_info.value.report
    assert report is not None
    assert report.suspected_scanned_pages == (1,)
    assert report.image_pages == (1,)
    assert report.errors


def test_corrupt_and_non_pdf_inputs_raise_invalid_document_error() -> None:
    parser = PdfDocumentParser()
    with pytest.raises(InvalidDocumentError):
        parser.parse(b"not a pdf at all")
    with pytest.raises(InvalidDocumentError):
        parser.parse(b"%PDF-1.4\ntruncated garbage without xref")
    with pytest.raises(InvalidDocumentError):
        parser.parse(b"")


def test_encrypted_pdf_raises_encrypted_document_error() -> None:
    pdf_bytes = build_pdf(
        [PageSpec(items=(TextItem("Gizli metin.", x=72, y=700),))],
        encrypted=True,
    )
    with pytest.raises(EncryptedDocumentError):
        PdfDocumentParser().parse(pdf_bytes, source_name="locked.pdf")
