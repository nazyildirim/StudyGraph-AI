"""Test-only deterministic FakeEmbeddingProvider (never used in production)."""

from __future__ import annotations

from collections.abc import Sequence
import hashlib
import math

from app.rag.embedding.errors import (
    InvalidEmbeddingInputError,
    TokenLimitExceededError,
)


class FakeEmbeddingProvider:
    """Deterministic hash-based embedding provider strictly for unit/integration tests."""

    def __init__(
        self,
        *,
        model_name: str = "fake-test-embedding",
        dimension: int = 8,
        max_tokens: int = 64,
    ) -> None:
        self._model_name = model_name
        self._dimension = dimension
        self._max_tokens = max_tokens

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

    def count_tokens(self, text: str, *, is_query: bool = False) -> int:
        if not text or not text.strip():
            raise InvalidEmbeddingInputError("Text must not be blank.")
        # Whitespace token count + 2 (prefix + special tokens) for predictable tests.
        return len(text.split()) + 2

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            raise InvalidEmbeddingInputError("texts must not be empty.")
        return [self._embed_single(t, prefix="passage: ") for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_single(text, prefix="query: ")

    def _embed_single(self, text: str, *, prefix: str) -> list[float]:
        if not isinstance(text, str) or not text.strip():
            raise InvalidEmbeddingInputError("Text must not be blank.")
        tokens = self.count_tokens(text, is_query=(prefix == "query: "))
        if tokens > self._max_tokens:
            raise TokenLimitExceededError(tokens, self._max_tokens)

        # Deterministic unit vector from SHA-256 of prefixed text.
        digest = hashlib.sha256((prefix + text.strip()).encode("utf-8")).digest()
        raw = [
            ((digest[i % len(digest)] / 255.0) * 2.0) - 1.0
            for i in range(self._dimension)
        ]
        norm = math.sqrt(sum(v * v for v in raw)) or 1.0
        return [v / norm for v in raw]
