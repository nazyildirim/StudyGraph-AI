"""CourseEnrollment ORM model implementing `course_enrollments`.

Resolves the N:M relation between students (`users`) and `courses`.
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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class EnrollmentStatus(StrEnum):
    """Enrollment lifecycle values allowed by DATABASE_DESIGN.md."""

    ACTIVE = "active"
    COMPLETED = "completed"
    DROPPED = "dropped"


_ALLOWED_STATUSES_SQL = ", ".join(f"'{status.value}'" for status in EnrollmentStatus)


class CourseEnrollment(Base):
    """A student's enrollment in a course (one row per student and course).

    Both foreign keys use ON DELETE CASCADE: removing a student or a course
    removes the enrollment rows that only exist to link them.
    """

    __tablename__ = "course_enrollments"
    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "course_id",
            name="uq_course_enrollments_student_id_course_id",
        ),
        CheckConstraint(f"status IN ({_ALLOWED_STATUSES_SQL})", name="status"),
        # The unique constraint already serves lookups by student_id (leading
        # column); this index serves "who is enrolled in this course".
        Index("ix_course_enrollments_course_id", "course_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    course_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=EnrollmentStatus.ACTIVE.value,
        server_default=text("'active'"),
    )
