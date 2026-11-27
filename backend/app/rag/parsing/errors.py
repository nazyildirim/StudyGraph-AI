"""Domain errors raised by document parsers."""

from __future__ import annotations

from app.rag.domain.types import ExtractionReport


class DocumentParseError(Exception):
    """Base error for document parsing failures."""

    def __init__(
        self,
        message: str,
        *,
        report: ExtractionReport | None = None,
    ) -> None:
        super().__init__(message)
        self.report = report


class InvalidDocumentError(DocumentParseError):
    """Raised when input is corrupt, truncated, binary, or unsupported."""


class EncryptedDocumentError(DocumentParseError):
    """Raised when a PDF is encrypted / password-protected."""


class EmptyDocumentError(DocumentParseError):
    """Raised when a document contains no extractable text."""
