"""VectorStore Protocol for course-scoped similarity search."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.rag.domain.types import RetrievedChunk


class VectorStore(Protocol):
    """Contract for searching embedded chunks within a single course."""

    def search(
        self,
        *,
        course_id: int,
        query_vector: Sequence[float],
        expected_model: str,
        expected_dim: int,
        top_k: int = 5,
    ) -> list[RetrievedChunk]: ...
