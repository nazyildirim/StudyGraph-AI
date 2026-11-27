"""MasteryRecord ORM model implementing `mastery_records`.

Aligned with docs/DATABASE_DESIGN.md §3.12.
Stores one current mastery row per `(student_id, learning_outcome_id)`.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MasteryRecord(Base):
    """Current mastery score and attempt count for a student on one outcome."""

    __tablename__ = "mastery_records"
    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "learning_outcome_id",
            name="uq_mastery_records_student_id_learning_outcome_id",
        ),
        CheckConstraint(
            "mastery_score >= 0 AND mastery_score <= 100",
            name="mastery_score_range",
        ),
        CheckConstraint("total_attempts >= 1", name="total_attempts_positive"),
        Index("ix_mastery_records_learning_outcome_id", "learning_outcome_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    learning_outcome_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("learning_outcomes.id", ondelete="CASCADE"),
        nullable=False,
    )
    mastery_score: Mapped[float] = mapped_column(Float, nullable=False)
    total_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    last_assessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
