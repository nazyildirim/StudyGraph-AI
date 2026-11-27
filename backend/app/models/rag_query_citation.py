"""RagQueryCitation ORM model implementing `rag_query_citations` (Issue #8)."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RagQueryCitation(Base):
    """Links an answer to a chunk that was actually used as a source.

    Both foreign keys cascade. Note: replacing a material's chunks deletes the
    citations that pointed at them, so re-indexing must be a deliberate action.
    """

    __tablename__ = "rag_query_citations"
    __table_args__ = (
        UniqueConstraint(
            "query_id",
            "chunk_id",
            name="uq_rag_query_citations_query_id_chunk_id",
        ),
        CheckConstraint(
            "relevance_score IS NULL OR (relevance_score >= 0 AND relevance_score <= 1)",
            name="relevance_score_range",
        ),
        Index("ix_rag_query_citations_chunk_id", "chunk_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    query_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("rag_queries.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("material_chunks.id", ondelete="CASCADE"),
        nullable=False,
    )
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
