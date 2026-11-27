"""CourseMaterial ORM model implementing `course_materials` (Issue #8)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.rag.domain.types import ProcessingStatus

_ALLOWED_STATUSES_SQL = ", ".join(f"'{status.value}'" for status in ProcessingStatus)


class CourseMaterial(Base):
    """A document uploaded for a course and processed for RAG.

    Differences from DATABASE_DESIGN.md (documented in the Phase 1 report):
    - `content_hash` (SHA-256 hex) rejects re-uploading identical content to the
      same course.
    - `error_message` and `extraction_report` store ingestion diagnostics.
    - `unverified_outcome_ref` keeps the outcome identifier supplied by the
      client. It is NOT a foreign key because `learning_outcomes` does not
      exist yet, and it must never be trusted as a validated relation.
    """

    __tablename__ = "course_materials"
    __table_args__ = (
        UniqueConstraint(
            "course_id",
            "content_hash",
            name="uq_course_materials_course_id_content_hash",
        ),
        CheckConstraint(
            f"processing_status IN ({_ALLOWED_STATUSES_SQL})",
            name="processing_status",
        ),
        CheckConstraint(
            "file_size_bytes IS NULL OR file_size_bytes >= 0",
            name="file_size_non_negative",
        ),
        Index("ix_course_materials_course_id", "course_id"),
        Index("ix_course_materials_uploaded_by", "uploaded_by"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    uploaded_by: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    unverified_outcome_ref: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    processing_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=ProcessingStatus.PENDING.value,
        server_default=text("'pending'"),
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_report: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
