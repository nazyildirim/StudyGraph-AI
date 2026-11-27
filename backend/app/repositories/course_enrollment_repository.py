"""CourseEnrollment persistence abstraction and SQLAlchemy implementation."""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.course_enrollment import CourseEnrollment, EnrollmentStatus
from app.repositories.errors import (
    EnrollmentAlreadyExistsError,
    RelatedRecordNotFoundError,
    is_foreign_key_violation,
    is_unique_violation,
)

ENROLLMENT_UNIQUE_CONSTRAINT = "uq_course_enrollments_student_id_course_id"


class CourseEnrollmentRepository(Protocol):
    """Repository contract for student-course enrollments."""

    def get(self, student_id: int, course_id: int) -> CourseEnrollment | None: ...

    def create(
        self,
        *,
        student_id: int,
        course_id: int,
        status: EnrollmentStatus = EnrollmentStatus.ACTIVE,
    ) -> CourseEnrollment: ...

    def has_active_enrollment(self, student_id: int, course_id: int) -> bool: ...


class SqlAlchemyCourseEnrollmentRepository:
    """SQLAlchemy 2.0 implementation of CourseEnrollmentRepository."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, student_id: int, course_id: int) -> CourseEnrollment | None:
        return self._session.execute(
            select(CourseEnrollment).where(
                CourseEnrollment.student_id == student_id,
                CourseEnrollment.course_id == course_id,
            )
        ).scalar_one_or_none()

    def create(
        self,
        *,
        student_id: int,
        course_id: int,
        status: EnrollmentStatus = EnrollmentStatus.ACTIVE,
    ) -> CourseEnrollment:
        enrollment = CourseEnrollment(
            student_id=student_id,
            course_id=course_id,
            status=EnrollmentStatus(status).value,
        )
        self._session.add(enrollment)
        try:
            self._session.commit()
        except IntegrityError as error:
            self._session.rollback()
            if is_unique_violation(error, ENROLLMENT_UNIQUE_CONSTRAINT):
                raise EnrollmentAlreadyExistsError(
                    f"student={student_id} course={course_id}"
                ) from error
            if is_foreign_key_violation(error):
                raise RelatedRecordNotFoundError("student or course") from error
            raise
        return enrollment

    def has_active_enrollment(self, student_id: int, course_id: int) -> bool:
        found = self._session.execute(
            select(CourseEnrollment.id).where(
                CourseEnrollment.student_id == student_id,
                CourseEnrollment.course_id == course_id,
                CourseEnrollment.status == EnrollmentStatus.ACTIVE.value,
            )
        ).first()
        return found is not None
