"""QuestionOption ORM model implementing `question_options`.

Aligned with docs/DATABASE_DESIGN.md §3.7.
- Enforces unique `order_index` per question.
- Enforces at most one `is_correct = true` option per question via a PostgreSQL
  partial unique index (at-least-one correct option is enforced at the service
  and transaction boundary).
- Exposes `UNIQUE(id, question_id)` so `student_responses` can enforce option
  ownership via a composite foreign key.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class QuestionOption(Base):
    """An answer choice belonging to a question."""

    __tablename__ = "question_options"
    __table_args__ = (
        UniqueConstraint(
            "question_id",
            "order_index",
            name="uq_question_options_question_id_order_index",
        ),
        # Enables composite FK from `student_responses(selected_option_id, question_id)`.
        UniqueConstraint(
            "id",
            "question_id",
            name="uq_question_options_id_question_id",
        ),
        CheckConstraint("order_index >= 0", name="order_index_non_negative"),
        Index(
            "uq_question_options_one_correct_per_question",
            "question_id",
            unique=True,
            postgresql_where=text("is_correct = true"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    option_text: Mapped[str] = mapped_column(Text, nullable=False)
    is_correct: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    order_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
