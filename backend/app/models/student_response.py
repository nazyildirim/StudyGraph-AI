"""StudentResponse ORM model implementing `student_responses`.

Aligned with docs/DATABASE_DESIGN.md §3.11 with composite foreign keys that
enforce at the PostgreSQL layer:
1. `(student_assessment_id, assessment_id)` matches `student_assessments`.
2. `(assessment_id, question_id)` exists in `assessment_questions` (a student
   can only answer questions actually assigned to their assessment) with
   `ON DELETE RESTRICT` to protect historical records.
3. `(selected_option_id, question_id)` exists in `question_options` (when
   answered, the chosen option must belong to that exact question) with
   `ON DELETE RESTRICT`.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StudentResponse(Base):
    """A student's graded response to one question in an assessment attempt."""

    __tablename__ = "student_responses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["student_assessment_id", "assessment_id"],
            ["student_assessments.id", "student_assessments.assessment_id"],
            name="fk_student_responses_attempt_assessment",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["assessment_id", "question_id"],
            ["assessment_questions.assessment_id", "assessment_questions.question_id"],
            name="fk_student_responses_assessment_question",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["selected_option_id", "question_id"],
            ["question_options.id", "question_options.question_id"],
            name="fk_student_responses_option_question",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "student_assessment_id",
            "question_id",
            name="uq_student_responses_attempt_question",
        ),
        CheckConstraint("score_earned >= 0", name="score_earned_non_negative"),
        CheckConstraint(
            "(selected_option_id IS NOT NULL) OR (is_correct = false AND score_earned = 0)",
            name="unanswered_cannot_be_correct",
        ),
        Index("ix_student_responses_question_id", "question_id"),
        Index(
            "ix_student_responses_assessment_id_question_id",
            "assessment_id",
            "question_id",
        ),
        Index("ix_student_responses_selected_option_id", "selected_option_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_assessment_id: Mapped[int] = mapped_column(Integer, nullable=False)
    assessment_id: Mapped[int] = mapped_column(Integer, nullable=False)
    question_id: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_option_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    score_earned: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        server_default=text("0.0"),
    )
    answered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
