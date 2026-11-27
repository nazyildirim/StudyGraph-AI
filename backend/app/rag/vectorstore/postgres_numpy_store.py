"""PostgreSQL + NumPy cosine similarity VectorStore implementation."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.course_material import CourseMaterial
from app.models.material_chunk import MaterialChunk
from app.rag.domain.types import ProcessingStatus, RetrievalMethod, RetrievedChunk
from app.rag.embedding.errors import EmbeddingModelMismatchError
from app.rag.embedding.validation import (
    deserialize_vector,
    l2_normalize_matrix,
    validate_vector,
)

DEFAULT_MAX_TOP_K = 100


class PostgresNumpyVectorStore:
    """Course-scoped cosine similarity search over float32 BYTEA embeddings.

    Security & isolation:
    - Candidate chunks are filtered at the SQL level by `course_id` and
      `processing_status = 'processed'`, so chunks from other courses or
      failed/pending materials never enter scoring.
    - User-level access control (`CourseAccessPolicy`) is enforced by the
      retrieval layer in Phase 4 before calling `search()`.
    """

    def __init__(
        self,
        session: Session,
        *,
        max_top_k: int = DEFAULT_MAX_TOP_K,
    ) -> None:
        if max_top_k <= 0:
            raise ValueError("max_top_k must be > 0.")
        self._session = session
        self._max_top_k = max_top_k

    def search(
        self,
        *,
        course_id: int,
        query_vector: Sequence[float],
        expected_model: str,
        expected_dim: int,
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        if course_id <= 0:
            raise ValueError("course_id must be > 0.")
        if not expected_model or not expected_model.strip():
            raise ValueError("expected_model must not be blank.")
        if top_k <= 0 or top_k > self._max_top_k:
            raise ValueError(f"top_k must be between 1 and {self._max_top_k}.")

        q_arr = validate_vector(query_vector, expected_dim)
        q_norm = q_arr / float(np.linalg.norm(q_arr))

        rows = self._session.execute(
            select(
                MaterialChunk.id,
                MaterialChunk.material_id,
                CourseMaterial.title,
                MaterialChunk.content,
                MaterialChunk.page_start,
                MaterialChunk.page_end,
                MaterialChunk.embedding,
                MaterialChunk.embedding_model,
                MaterialChunk.embedding_dim,
            )
            .join(CourseMaterial, CourseMaterial.id == MaterialChunk.material_id)
            .where(
                CourseMaterial.course_id == course_id,
                CourseMaterial.processing_status == ProcessingStatus.PROCESSED.value,
                MaterialChunk.embedding.is_not(None),
            )
            .order_by(MaterialChunk.id)
        ).all()

        if not rows:
            return []

        vectors: list[np.ndarray] = []
        for row in rows:
            if row.embedding_model != expected_model or row.embedding_dim != expected_dim:
                raise EmbeddingModelMismatchError(
                    f"Chunk {row.id} uses ({row.embedding_model}, dim={row.embedding_dim}), "
                    f"expected ({expected_model}, dim={expected_dim})."
                )
            vectors.append(deserialize_vector(row.embedding, expected_dim))

        matrix = l2_normalize_matrix(np.vstack(vectors))
        raw_scores = matrix @ q_norm
        clamped_scores = np.clip(raw_scores, -1.0, 1.0)

        scored = [
            RetrievedChunk(
                chunk_id=row.id,
                material_id=row.material_id,
                material_title=row.title,
                content=row.content,
                page_start=row.page_start,
                page_end=row.page_end,
                score=float(score),
                course_id=course_id,
                retrieval_method=RetrievalMethod.SEMANTIC_E5.value,
            )
            for row, score in zip(rows, clamped_scores, strict=True)
        ]

        # Deterministic tie-breaking: higher score first, then lower chunk_id.
        scored.sort(key=lambda hit: (-hit.score, hit.chunk_id))
        return scored[:top_k]
