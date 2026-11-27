"""EmbeddingProvider Protocol for provider-independent embeddings."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class EmbeddingProvider(Protocol):
    """Contract implemented by embedding providers (ONNX E5, test fakes)."""

    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    @property
    def max_tokens(self) -> int: ...

    def count_tokens(self, text: str, *, is_query: bool = False) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...
