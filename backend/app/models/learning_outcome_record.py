"""LearningOutcomeRecord ORM model implementing `learning_outcomes`.

Shared infrastructure table aligned with docs/DATABASE_DESIGN.md §3.4.
Named `LearningOutcomeRecord` to avoid colliding with the in-memory domain
dataclass `app.domain.learning_outcome.LearningOutcome` owned by Issue #4/#5.
"""

from __future__ import annotations

from datetime import datetime

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


class LearningOutcomeRecord(Base):
    """Persisted learning outcome belonging to a single course."""

    __tablename__ = "learning_outcomes"
    __table_args__ = (
        UniqueConstraint(
            "course_id",
            "code",
            name="uq_learning_outcomes_course_id_code",
        ),
        # Enables composite FKs from `prerequisites` and `questions` to enforce
        # same-course isolation at the database level.
        UniqueConstraint(
            "id",
            "course_id",
            name="uq_learning_outcomes_id_course_id",
        ),
        CheckConstraint("order_index >= 0", name="order_index_non_negative"),
        Index(
            "ix_learning_outcomes_course_id_order_index",
            "course_id",
            "order_index",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    created_at: Mapped[datetime] = mapped_column(
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
