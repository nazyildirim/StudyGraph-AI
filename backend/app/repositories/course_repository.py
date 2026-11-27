"""Course persistence abstraction and SQLAlchemy 2.0 implementation.

Transaction convention (same as `SqlAlchemyUserRepository`): mutating methods
own commit and rollback; read methods never commit.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.course import Course
from app.repositories.errors import (
    CourseCodeAlreadyExistsError,
    RelatedRecordNotFoundError,
    is_foreign_key_violation,
    is_unique_violation,
)

COURSE_CODE_UNIQUE_CONSTRAINT = "uq_courses_code"


class CourseRepository(Protocol):
    """Repository contract for Course persistence."""

    def get_by_id(self, course_id: int) -> Course | None: ...

    def get_by_code(self, code: str) -> Course | None: ...

    def create(
        self,
        *,
        code: str,
        title: str,
        instructor_id: int,
        description: str | None = None,
        is_active: bool = True,
    ) -> Course: ...


class SqlAlchemyCourseRepository:
    """SQLAlchemy 2.0 implementation of CourseRepository."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, course_id: int) -> Course | None:
        return self._session.get(Course, course_id)

    def get_by_code(self, code: str) -> Course | None:
        return self._session.execute(
            select(Course).where(Course.code == code)
        ).scalar_one_or_none()

    def create(
        self,
        *,
        code: str,
        title: str,
        instructor_id: int,
        description: str | None = None,
        is_active: bool = True,
    ) -> Course:
        course = Course(
            code=code,
            title=title,
            description=description,
            instructor_id=instructor_id,
            is_active=is_active,
        )
        self._session.add(course)
        try:
            self._session.commit()
        except IntegrityError as error:
            self._session.rollback()
            if is_unique_violation(error, COURSE_CODE_UNIQUE_CONSTRAINT):
                raise CourseCodeAlreadyExistsError(code) from error
            if is_foreign_key_violation(error):
                raise RelatedRecordNotFoundError("instructor") from error
            raise
        return course
