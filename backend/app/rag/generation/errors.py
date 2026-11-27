"""Domain errors for LLM generation and citation validation."""

from __future__ import annotations


class LLMError(Exception):
    """Base error for LLM client failures."""


class LLMConnectionError(LLMError):
    """Raised when the local LLM server is unreachable or returns an HTTP error."""


class LLMTimeoutError(LLMError):
    """Raised when the LLM request exceeds the configured timeout."""


class LLMInvalidResponseError(LLMError):
    """Raised when the LLM returns malformed JSON, missing fields, or blank text."""


class CitationValidationError(Exception):
    """Raised when LLM citations are unknown, cross-course, or missing."""
