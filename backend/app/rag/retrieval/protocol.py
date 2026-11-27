"""ChunkRetriever Protocol for interchangeable retrieval strategies."""

from __future__ import annotations

from typing import Protocol

from app.rag.domain.types import RetrievalMethod, RetrievedChunk


class ChunkRetriever(Protocol):
    """Contract implemented by retrieval strategies (Semantic E5, BM25)."""

    @property
    def method(self) -> RetrievalMethod: ...

    def retrieve(
        self,
        *,
        course_id: int,
        query: str,
        top_k: int,
        min_score: float,
    ) -> list[RetrievedChunk]: ...
