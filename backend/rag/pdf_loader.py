"""Backward-compatible wrapper for the legacy PDF loader prototype.

Delegates all PDF parsing to `app.rag.parsing.PdfDocumentParser` so no
parsing logic is duplicated.
"""

from __future__ import annotations

from pathlib import Path

from app.rag.parsing.pdf_parser import PdfDocumentParser


def extract_text(pdf_path: str | Path) -> str:
    """Extract full text from a PDF file using `PdfDocumentParser`."""
    document = PdfDocumentParser().parse(pdf_path)
    return document.full_text
