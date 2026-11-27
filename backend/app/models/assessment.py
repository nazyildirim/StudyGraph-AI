"""Assessment ORM model implementing `assessments` from DATABASE_DESIGN.md §3.8."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AssessmentType(StrEnum):
    """Supported assessment types aligned with DATABASE_DESIGN.md."""

    DIAGNOSTIC = "diagnostic"
    PRACTICE = "practice"
    REVIEW = "review"
    FINAL = "final"


_ALLOWED_TYPES_SQL = ", ".join(f"'{item.value}'" for item in AssessmentType)


class Assessment(Base):
    """An assessment/exam belonging to a single course."""

    __tablename__ = "assessments"
    __table_args__ = (
        # Enables composite FK from `assessment_questions` for same-course enforcement.
        UniqueConstraint(
            "id",
            "course_id",
            name="uq_assessments_id_course_id",
        ),
        CheckConstraint(
            f"assessment_type IN ({_ALLOWED_TYPES_SQL})",
            name="assessment_type",
        ),
        CheckConstraint(
            "time_limit_minutes IS NULL OR time_limit_minutes > 0",
            name="time_limit_positive",
        ),
        Index("ix_assessments_course_id_type", "course_id", "assessment_type"),
        Index("ix_assessments_created_by", "created_by"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    assessment_type: Mapped[str] = mapped_column(String(30), nullable=False)
    time_limit_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
