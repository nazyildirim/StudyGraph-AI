"""MaterialChunk ORM model implementing `material_chunks` (Issue #8)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MaterialChunk(Base):
    """A text chunk of a material, with source page info and optional embedding.

    Differences from DATABASE_DESIGN.md:
    - `page_number` is replaced by `page_start`/`page_end` because a chunk may
      span several pages.
    - `learning_outcome_id` is intentionally absent until `learning_outcomes`
      exists; it will be added with a real foreign key in a later migration.
    - `embedding` (float32 BYTEA), `embedding_model`, and `embedding_dim` are
      nullable together so pre-existing unembedded rows remain valid while
      partially populated embedding metadata is rejected at the DB level.
    """

    __tablename__ = "material_chunks"
    __table_args__ = (
        UniqueConstraint(
            "material_id",
            "chunk_index",
            name="uq_material_chunks_material_id_chunk_index",
        ),
        CheckConstraint("chunk_index >= 0", name="chunk_index_non_negative"),
        CheckConstraint(
            "page_start IS NULL OR page_start >= 1",
            name="page_start_positive",
        ),
        CheckConstraint(
            "page_end IS NULL OR (page_start IS NOT NULL AND page_end >= page_start)",
            name="page_range_valid",
        ),
        CheckConstraint(
            "(embedding IS NULL AND embedding_model IS NULL AND embedding_dim IS NULL) "
            "OR (embedding IS NOT NULL AND embedding_model IS NOT NULL AND embedding_dim IS NOT NULL)",
            name="embedding_fields_consistent",
        ),
        CheckConstraint(
            "embedding_dim IS NULL OR embedding_dim > 0",
            name="embedding_dim_positive",
        ),
        CheckConstraint(
            "embedding IS NULL OR octet_length(embedding) = embedding_dim * 4",
            name="embedding_byte_length",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    material_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("course_materials.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_dim: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
