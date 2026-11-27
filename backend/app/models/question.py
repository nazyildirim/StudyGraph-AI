"""Question ORM model implementing `questions` from docs/DATABASE_DESIGN.md §3.6.

Includes soft-delete (`is_active`, `archived_at`) and immutable version lineage
(`root_question_id`, `previous_version_id`, `version_number`) so editing or
deleting questions that were included in any assessment never mutates historical
exam records and retest selection can recognize prior versions of a question.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
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


class QuestionType(StrEnum):
    """Supported question types aligned with DATABASE_DESIGN.md."""

    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"


class DifficultyLevel(StrEnum):
    """Supported question difficulty levels aligned with DATABASE_DESIGN.md."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


_ALLOWED_TYPES_SQL = ", ".join(f"'{item.value}'" for item in QuestionType)
_ALLOWED_DIFFICULTIES_SQL = ", ".join(f"'{item.value}'" for item in DifficultyLevel)


class Question(Base):
    """A question tied to one learning outcome within one course."""

    __tablename__ = "questions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["learning_outcome_id", "course_id"],
            ["learning_outcomes.id", "learning_outcomes.course_id"],
            name="fk_questions_outcome_course",
            ondelete="RESTRICT",
        ),
        # Enables composite FK from `assessment_questions` to guarantee every
        # question assigned to an assessment belongs to the same course.
        UniqueConstraint(
            "id",
            "course_id",
            name="uq_questions_id_course_id",
        ),
        UniqueConstraint(
            "root_question_id",
            "version_number",
            name="uq_questions_root_question_id_version_number",
        ),
        UniqueConstraint(
            "previous_version_id",
            name="uq_questions_previous_version_id",
        ),
        CheckConstraint(
            f"question_type IN ({_ALLOWED_TYPES_SQL})",
            name="question_type",
        ),
        CheckConstraint(
            f"difficulty_level IN ({_ALLOWED_DIFFICULTIES_SQL})",
            name="difficulty_level",
        ),
        CheckConstraint("points > 0", name="points_positive"),
        CheckConstraint("version_number >= 1", name="version_number_positive"),
        CheckConstraint(
            "(version_number = 1 AND root_question_id IS NULL AND previous_version_id IS NULL) "
            "OR (version_number > 1 AND root_question_id IS NOT NULL AND previous_version_id IS NOT NULL)",
            name="version_lineage_consistent",
        ),
        CheckConstraint(
            "root_question_id IS NULL OR root_question_id != id",
            name="root_not_self",
        ),
        CheckConstraint(
            "previous_version_id IS NULL OR previous_version_id != id",
            name="previous_not_self",
        ),
        CheckConstraint(
            "(is_active = true AND archived_at IS NULL) "
            "OR (is_active = false AND archived_at IS NOT NULL)",
            name="active_archived_consistent",
        ),
        Index("ix_questions_course_id_is_active", "course_id", "is_active"),
        Index("ix_questions_learning_outcome_id", "learning_outcome_id"),
        Index("ix_questions_created_by", "created_by"),
        Index("ix_questions_root_question_id", "root_question_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    learning_outcome_id: Mapped[int] = mapped_column(Integer, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=QuestionType.MULTIPLE_CHOICE.value,
        server_default=text("'multiple_choice'"),
    )
    difficulty_level: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=DifficultyLevel.MEDIUM.value,
        server_default=text("'medium'"),
    )
    points: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=1.0,
        server_default=text("1.0"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    root_question_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("questions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    previous_version_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("questions.id", ondelete="RESTRICT"),
        nullable=True,
    )
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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
