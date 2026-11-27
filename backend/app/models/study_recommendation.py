"""StudyRecommendation ORM model implementing `study_recommendations`.

Aligned with docs/DATABASE_DESIGN.md §3.13, extended to preserve all
`RecommendationEngine` statuses (`completed`, `review`, `study`, `blocked`)
alongside the workflow statuses (`pending`, `in_progress`) so `blocked`
recommendations are never lost on persistence.
"""

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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RecommendationStatus(StrEnum):
    """Allowed persisted recommendation statuses."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REVIEW = "review"
    STUDY = "study"
    BLOCKED = "blocked"


_ALLOWED_STATUSES_SQL = ", ".join(
    f"'{item.value}'" for item in RecommendationStatus
)


class StudyRecommendation(Base):
    """Personalized learning outcome recommendation for a student."""

    __tablename__ = "study_recommendations"
    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "learning_outcome_id",
            name="uq_study_recommendations_student_outcome",
        ),
        CheckConstraint("priority_order >= 1", name="priority_order_positive"),
        CheckConstraint(
            f"status IN ({_ALLOWED_STATUSES_SQL})",
            name="status",
        ),
        Index(
            "ix_study_recommendations_student_id_priority",
            "student_id",
            "priority_order",
        ),
        Index(
            "ix_study_recommendations_learning_outcome_id",
            "learning_outcome_id",
        ),
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
    priority_order: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=RecommendationStatus.PENDING.value,
        server_default=text("'pending'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
