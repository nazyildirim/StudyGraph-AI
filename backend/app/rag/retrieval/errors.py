"""Domain errors for RAG retrieval."""

from __future__ import annotations


class RetrievalError(Exception):
    """Base error for retrieval operations."""


class InvalidQueryError(RetrievalError):
    """Raised when a query is blank or exceeds the allowed length."""


class RetrievalBackendUnavailableError(RetrievalError):
    """Raised when the retrieval backend (e.g. local ONNX model) is unavailable."""
