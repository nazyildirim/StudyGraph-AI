"""Domain errors for embedding generation and vector storage."""

from __future__ import annotations


class EmbeddingError(Exception):
    """Base error for embedding provider failures."""


class ModelNotFoundError(EmbeddingError):
    """Raised when local ONNX model or tokenizer files are missing."""


class InvalidEmbeddingInputError(EmbeddingError):
    """Raised when input text list is empty or contains blank strings."""


class TokenLimitExceededError(EmbeddingError):
    """Raised when input exceeds the embedding model's token capacity."""

    def __init__(self, token_count: int, max_tokens: int) -> None:
        super().__init__(
            f"Input token count ({token_count}) exceeds model max_tokens ({max_tokens})."
        )
        self.token_count = token_count
        self.max_tokens = max_tokens


class InvalidEmbeddingVectorError(EmbeddingError):
    """Raised on NaN, Infinity, zero-norm, or wrong-dimension vectors."""


class EmbeddingModelMismatchError(EmbeddingError):
    """Raised when stored chunk embeddings do not match the active model/dim."""
