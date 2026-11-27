"""Semantic retriever backed by `EmbeddingProvider` + `VectorStore`.

Note on similarity scores:
    Raw cosine similarity is a geometric vector similarity metric in [-1, 1],
    NOT a probability of correctness or an answer confidence percentage.
    Threshold `min_score` is applied directly on the raw cosine similarity
    scale (no rescaling is performed).
"""

from __future__ import annotations

import math

from app.rag.domain.types import RetrievalMethod, RetrievedChunk
from app.rag.embedding.protocol import EmbeddingProvider
from app.rag.retrieval.errors import InvalidQueryError
from app.rag.vectorstore.protocol import VectorStore

DEFAULT_SEMANTIC_TOP_K = 5
# Calibrated on a 25-query labeled synthetic TR/EN/code study with
# intfloat/multilingual-e5-small (raw cosine scale): 0.81 gave 15/15 TP (0 FN)
# while rejecting all unrelated queries and lower-scoring unanswered queries.
DEFAULT_SEMANTIC_MIN_SCORE = 0.81
DEFAULT_MAX_QUERY_LENGTH = 2000


class SemanticRetriever:
    """Retrieves course chunks using E5 embeddings and cosine similarity."""

    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        max_query_length: int = DEFAULT_MAX_QUERY_LENGTH,
    ) -> None:
        if max_query_length <= 0:
            raise ValueError("max_query_length must be > 0.")
        self._embeddings = embedding_provider
        self._store = vector_store
        self._max_query_length = max_query_length

    @property
    def method(self) -> RetrievalMethod:
        return RetrievalMethod.SEMANTIC_E5

    def retrieve(
        self,
        *,
        course_id: int,
        query: str,
        top_k: int = DEFAULT_SEMANTIC_TOP_K,
        min_score: float = DEFAULT_SEMANTIC_MIN_SCORE,
    ) -> list[RetrievedChunk]:
        cleaned = _validate_query(query, self._max_query_length)
        if course_id <= 0:
            raise ValueError("course_id must be > 0.")
        if top_k <= 0:
            raise ValueError("top_k must be > 0.")
        if not math.isfinite(min_score) or not (-1.0 <= min_score <= 1.0):
            raise ValueError("min_score for cosine similarity must be in [-1.0, 1.0].")

        query_vector = self._embeddings.embed_query(cleaned)
        raw_hits = self._store.search(
            course_id=course_id,
            query_vector=query_vector,
            expected_model=self._embeddings.model_name,
            expected_dim=self._embeddings.dimension,
            top_k=top_k,
        )

        deduped: list[RetrievedChunk] = []
        seen_chunk_ids: set[int] = set()
        for hit in raw_hits:
            if not math.isfinite(hit.score):
                raise ValueError("VectorStore returned a non-finite similarity score.")
            if hit.chunk_id in seen_chunk_ids:
                continue
            if hit.score < min_score:
                continue
            seen_chunk_ids.add(hit.chunk_id)
            deduped.append(
                RetrievedChunk(
                    chunk_id=hit.chunk_id,
                    material_id=hit.material_id,
                    material_title=hit.material_title,
                    content=hit.content,
                    page_start=hit.page_start,
                    page_end=hit.page_end,
                    score=float(hit.score),
                    course_id=course_id,
                    retrieval_method=RetrievalMethod.SEMANTIC_E5.value,
                )
            )

        deduped.sort(key=lambda item: (-item.score, item.chunk_id))
        return deduped[:top_k]


def _validate_query(query: str, max_length: int) -> str:
    if not isinstance(query, str) or not query.strip():
        raise InvalidQueryError("Query must not be blank.")
    cleaned = query.strip()
    if len(cleaned) > max_length:
        raise InvalidQueryError(
            f"Query length ({len(cleaned)}) exceeds maximum ({max_length})."
        )
    return cleaned
