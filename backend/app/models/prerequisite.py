"""Prerequisite ORM model implementing `prerequisites` (DAG edges).

Shared infrastructure table aligned with docs/DATABASE_DESIGN.md §3.5.
Uses `course_id` + composite foreign keys to `learning_outcomes(id, course_id)`
so cross-course prerequisite edges are impossible at the database level.
Cycle detection (DAG validation) is enforced in the application layer.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Prerequisite(Base):
    """Directed prerequisite edge between two outcomes in the same course."""

    __tablename__ = "prerequisites"
    __table_args__ = (
        ForeignKeyConstraint(
            ["prerequisite_outcome_id", "course_id"],
            ["learning_outcomes.id", "learning_outcomes.course_id"],
            name="fk_prerequisites_prereq_outcome_course",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["dependent_outcome_id", "course_id"],
            ["learning_outcomes.id", "learning_outcomes.course_id"],
            name="fk_prerequisites_dep_outcome_course",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "prerequisite_outcome_id",
            "dependent_outcome_id",
            name="uq_prerequisites_prerequisite_dependent",
        ),
        CheckConstraint(
            "prerequisite_outcome_id != dependent_outcome_id",
            name="no_self_reference",
        ),
        Index("ix_prerequisites_course_id", "course_id"),
        Index(
            "ix_prerequisites_dependent_outcome_id",
            "dependent_outcome_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    prerequisite_outcome_id: Mapped[int] = mapped_column(Integer, nullable=False)
    dependent_outcome_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
