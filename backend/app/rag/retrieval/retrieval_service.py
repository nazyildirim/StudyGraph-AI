"""CourseRetrievalService: access-first retrieval orchestration with safe fallback.

Execution order (strictly enforced):
1. `CourseAccessPolicy.check_read_access(user, course_id)` — before any
   embedding or vector/BM25 query. Unauthorized users raise
   `ResourceNotFoundError` and NEVER trigger fallback.
2. Validate query length, `top_k`, and thresholds.
3. Run primary retriever (`SemanticRetriever` by default).
4. Safe fallback ONLY on explicit model unavailability (`ModelNotFoundError`):
   - Never falls back on access denial, invalid queries, or DB errors.
   - Never falls back when E5 returns zero chunks above `min_score`
     (respects the semantic threshold; returns `RetrievalStatus.NO_SOURCES`).
"""

from __future__ import annotations

import math

from app.authorization.course_access_policy import CourseAccessPolicy
from app.models.user import User
from app.rag.domain.types import RetrievalResult, RetrievalStatus
from app.rag.embedding.errors import ModelNotFoundError
from app.rag.retrieval.bm25 import DEFAULT_BM25_MIN_SCORE
from app.rag.retrieval.errors import (
    InvalidQueryError,
    RetrievalBackendUnavailableError,
)
from app.rag.retrieval.protocol import ChunkRetriever
from app.rag.retrieval.semantic_retriever import (
    DEFAULT_MAX_QUERY_LENGTH,
    DEFAULT_SEMANTIC_MIN_SCORE,
    DEFAULT_SEMANTIC_TOP_K,
)


class CourseRetrievalService:
    """Authorized, course-scoped retrieval service for RAG."""

    def __init__(
        self,
        *,
        access_policy: CourseAccessPolicy,
        primary_retriever: ChunkRetriever,
        fallback_retriever: ChunkRetriever | None = None,
        default_top_k: int = DEFAULT_SEMANTIC_TOP_K,
        primary_min_score: float = DEFAULT_SEMANTIC_MIN_SCORE,
        fallback_min_score: float = DEFAULT_BM25_MIN_SCORE,
        max_query_length: int = DEFAULT_MAX_QUERY_LENGTH,
    ) -> None:
        if default_top_k <= 0:
            raise ValueError("default_top_k must be > 0.")
        if not math.isfinite(primary_min_score):
            raise ValueError("primary_min_score must be finite.")
        if not math.isfinite(fallback_min_score) or fallback_min_score < 0.0:
            raise ValueError("fallback_min_score must be finite and >= 0.0.")
        if max_query_length <= 0:
            raise ValueError("max_query_length must be > 0.")

        self._access = access_policy
        self._primary = primary_retriever
        self._fallback = fallback_retriever
        self._default_top_k = default_top_k
        self._primary_min_score = primary_min_score
        self._fallback_min_score = fallback_min_score
        self._max_query_length = max_query_length

    def retrieve(
        self,
        *,
        user: User,
        course_id: int,
        query: str,
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> RetrievalResult:
        # 1. Access check MUST happen before any embedding or store call.
        self._access.check_read_access(user, course_id)

        # 2. Validate query and parameters.
        if not isinstance(query, str) or not query.strip():
            raise InvalidQueryError("Query must not be blank.")
        cleaned = query.strip()
        if len(cleaned) > self._max_query_length:
            raise InvalidQueryError(
                f"Query length ({len(cleaned)}) exceeds maximum ({self._max_query_length})."
            )

        effective_top_k = self._default_top_k if top_k is None else top_k
        if effective_top_k <= 0:
            raise ValueError("top_k must be > 0.")
        effective_min_score = (
            self._primary_min_score if min_score is None else min_score
        )
        if not math.isfinite(effective_min_score):
            raise ValueError("min_score must be finite.")

        # 3. Primary retrieval with explicit-only model-unavailability fallback.
        try:
            chunks = self._primary.retrieve(
                course_id=course_id,
                query=cleaned,
                top_k=effective_top_k,
                min_score=effective_min_score,
            )
            method = self._primary.method
            fallback_used = False
            fallback_reason: str | None = None
        except ModelNotFoundError as error:
            if self._fallback is None:
                raise RetrievalBackendUnavailableError(
                    "Embedding model is unavailable and no fallback retriever is configured."
                ) from error
            chunks = self._fallback.retrieve(
                course_id=course_id,
                query=cleaned,
                top_k=effective_top_k,
                min_score=self._fallback_min_score,
            )
            method = self._fallback.method
            fallback_used = True
            fallback_reason = "embedding_model_unavailable"

        # 4. Distinguish OK vs NO_SOURCES clearly.
        status = RetrievalStatus.OK if chunks else RetrievalStatus.NO_SOURCES
        return RetrievalResult(
            status=status,
            course_id=course_id,
            method=method,
            chunks=tuple(chunks),
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
        )
