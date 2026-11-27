"""AssessmentQuestion ORM model implementing `assessment_questions`.

Aligned with docs/DATABASE_DESIGN.md §3.9 with two database-enforced invariants:
1. Composite FKs with `course_id` ensure a question from another course can
   never be attached to an assessment.
2. `ON DELETE RESTRICT` on `(question_id, course_id)` preserves historical
   assessments as soon as a question is included in any assessment.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AssessmentQuestion(Base):
    """Ordered association between an assessment and a question in the same course."""

    __tablename__ = "assessment_questions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["assessment_id", "course_id"],
            ["assessments.id", "assessments.course_id"],
            name="fk_assessment_questions_assessment_course",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["question_id", "course_id"],
            ["questions.id", "questions.course_id"],
            name="fk_assessment_questions_question_course",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "assessment_id",
            "question_id",
            name="uq_assessment_questions_assessment_id_question_id",
        ),
        UniqueConstraint(
            "assessment_id",
            "order_index",
            name="uq_assessment_questions_assessment_id_order_index",
        ),
        CheckConstraint("order_index >= 0", name="order_index_non_negative"),
        Index("ix_assessment_questions_question_id", "question_id"),
        Index("ix_assessment_questions_course_id", "course_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[int] = mapped_column(Integer, nullable=False)
    question_id: Mapped[int] = mapped_column(Integer, nullable=False)
    course_id: Mapped[int] = mapped_column(Integer, nullable=False)
    order_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
