"""Pytest compatibility tests for the legacy `backend/rag/pdf_loader.py` wrapper."""

from __future__ import annotations

from pathlib import Path

from rag.pdf_loader import extract_text
from tests.rag.pdf_factory import PageSpec, TextItem, build_pdf


def test_legacy_extract_text_reads_synthetic_pdf(tmp_path: Path) -> None:
    pdf_file = tmp_path / "sample.pdf"
    pdf_file.write_bytes(
        build_pdf(
            [
                PageSpec(items=(TextItem("Birinci sayfa metni.", x=72, y=700),)),
                PageSpec(items=(TextItem("Ikinci sayfa printf ornegi.", x=72, y=700),)),
            ]
        )
    )

    text = extract_text(pdf_file)
    assert "Birinci sayfa metni." in text
    assert "printf" in text
