"""Course-level authorization policy reusing Issue #6 roles and ownership rules.

Deny-by-default rules:
- Inactive or invalid users are denied.
- Unknown roles are denied.
- Non-existent or inactive courses are denied with `ResourceNotFoundError`
  (anti-enumeration, matching Issue #6's `OwnershipPolicy` -> HTTP 404).
- Student: requires an `active` enrollment in `course_enrollments`.
- Instructor: requires `course.instructor_id == user.id`.
- Admin: allowed on any existing active course.
"""

from __future__ import annotations

from app.authorization.ownership import (
    RESOURCE_NOT_FOUND_MESSAGE,
    ResourceNotFoundError,
    RoleAuthorizationError,
    parse_user_role,
)
from app.authorization.roles import Role
from app.models.course import Course
from app.models.user import User
from app.repositories.course_enrollment_repository import (
    CourseEnrollmentRepository,
)
from app.repositories.course_repository import CourseRepository


class CourseAccessPolicy:
    """Verifies whether an authenticated user may read a course's materials."""

    def __init__(
        self,
        *,
        course_repository: CourseRepository,
        enrollment_repository: CourseEnrollmentRepository,
    ) -> None:
        self._courses = course_repository
        self._enrollments = enrollment_repository

    def check_read_access(self, user: User, course_id: int) -> Course:
        """Verify read access or raise `ResourceNotFoundError` (deny by default)."""
        if course_id <= 0 or user is None or not getattr(user, "is_active", False):
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)

        role = parse_user_role(user)
        if role is None:
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)

        course = self._courses.get_by_id(course_id)
        if course is None or not course.is_active:
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)

        if role is Role.ADMIN:
            return course

        if role is Role.INSTRUCTOR:
            if course.instructor_id == user.id:
                return course
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)

        if role is Role.STUDENT:
            if self._enrollments.has_active_enrollment(user.id, course_id):
                return course
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)

        raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)

    def check_manage_access(self, user: User, course_id: int) -> Course:
        """Verify course management access (upload/delete materials).

        - Student: raises `RoleAuthorizationError` (HTTP 403).
        - Owning instructor or admin on an existing active course: allowed.
        - Inactive user, unknown role, missing/inactive course, or different
          instructor: raises `ResourceNotFoundError` (HTTP 404, non-disclosing).
        """
        if course_id <= 0 or user is None or not getattr(user, "is_active", False):
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)

        role = parse_user_role(user)
        if role is None:
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)
        if role is Role.STUDENT:
            raise RoleAuthorizationError("Insufficient role permissions.")

        course = self._courses.get_by_id(course_id)
        if course is None or not course.is_active:
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)

        if role is Role.ADMIN:
            return course
        if role is Role.INSTRUCTOR and course.instructor_id == user.id:
            return course

        raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)
