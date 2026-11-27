"""Document parsing package (PDF via pdfplumber and UTF-8 plain text)."""

from app.rag.parsing.errors import (
    DocumentParseError,
    EmptyDocumentError,
    EncryptedDocumentError,
    InvalidDocumentError,
)
from app.rag.parsing.pdf_parser import PdfDocumentParser
from app.rag.parsing.protocol import DocumentParser
from app.rag.parsing.text_parser import PlainTextParser

__all__ = [
    "DocumentParseError",
    "DocumentParser",
    "EmptyDocumentError",
    "EncryptedDocumentError",
    "InvalidDocumentError",
    "PdfDocumentParser",
    "PlainTextParser",
]
