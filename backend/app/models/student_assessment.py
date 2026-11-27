"""StudentAssessment ORM model implementing `student_assessments`.

Aligned with docs/DATABASE_DESIGN.md §3.10.
Exposes `UNIQUE(id, assessment_id)` so `student_responses` can verify via
composite FKs that every answered question was actually assigned to this
attempt's assessment.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StudentAssessmentStatus(StrEnum):
    """Lifecycle states of a student assessment attempt."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


_ALLOWED_STATUSES_SQL = ", ".join(
    f"'{item.value}'" for item in StudentAssessmentStatus
)


class StudentAssessment(Base):
    """A student's attempt on a specific assessment."""

    __tablename__ = "student_assessments"
    __table_args__ = (
        # Enables composite FK from `student_responses(student_assessment_id, assessment_id)`.
        UniqueConstraint(
            "id",
            "assessment_id",
            name="uq_student_assessments_id_assessment_id",
        ),
        CheckConstraint(
            f"status IN ({_ALLOWED_STATUSES_SQL})",
            name="status",
        ),
        CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 100)",
            name="score_range",
        ),
        CheckConstraint(
            "(status = 'completed' AND completed_at IS NOT NULL) "
            "OR (status != 'completed' AND completed_at IS NULL)",
            name="completed_at_consistent",
        ),
        Index(
            "ix_student_assessments_student_id_status",
            "student_id",
            "status",
        ),
        Index("ix_student_assessments_assessment_id", "assessment_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    assessment_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("assessments.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=StudentAssessmentStatus.IN_PROGRESS.value,
        server_default=text("'in_progress'"),
    )
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
