"""Application service for instructor/admin Question Bank management (Issue #7).

Architectural principles:
- SRP: Coordinates authorization, input mapping, transaction boundaries, and
  question bank repository calls; contains zero FastAPI/HTTP dependencies.
- DIP: Depends on `QuestionRepository`, `LearningOutcomeRepository`,
  `CourseAccessPolicy`, and `TransactionManager` abstractions.
- Transaction ownership: Owns commit/rollback via `TransactionManager.begin()`;
  repositories only flush and never commit independently.
- Security: Enforces `CourseAccessPolicy.check_manage_access` BEFORE any read
  or mutation, preventing students, inactive users, or non-owning instructors
  from accessing instructor question schemas (which contain `is_correct`).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Protocol

from sqlalchemy.orm import Session

from app.authorization.course_access_policy import CourseAccessPolicy
from app.authorization.ownership import (
    RESOURCE_NOT_FOUND_MESSAGE,
    ResourceNotFoundError,
)
from app.models.question import QuestionType
from app.models.user import User
from app.repositories.errors import (
    CrossCourseReferenceError,
    PaginationValidationError,
    QuestionNotFoundError,
)
from app.repositories.learning_outcome_repository import LearningOutcomeRepository
from app.repositories.question_repository import (
    QuestionOptionDraft,
    QuestionRepository,
)
from app.schemas.question import (
    QuestionCreateRequest,
    QuestionDeleteResponse,
    QuestionInstructorResponse,
    QuestionUpdateRequest,
    QuestionUpdateResponse,
)


class TransactionManager(Protocol):
    """Unit-of-Work abstraction owning transaction commit and rollback."""

    def begin(self) -> AbstractContextManager[None]: ...


class SqlAlchemyTransactionManager:
    """SQLAlchemy Session-backed Unit-of-Work transaction manager.

    Commits the active session transaction on clean exit and rolls back on any
    exception, working cleanly even when prior read dependencies (such as
    `get_current_user` or `CourseAccessPolicy`) autobegan a read transaction
    on the same request-scoped `Session`.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    @contextmanager
    def begin(self) -> Iterator[None]:
        try:
            yield
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise


def _to_option_drafts(
    payload: QuestionCreateRequest | QuestionUpdateRequest,
) -> list[QuestionOptionDraft]:
    return [
        QuestionOptionDraft(
            option_text=opt.option_text,
            is_correct=opt.is_correct,
            order_index=opt.order_index,
        )
        for opt in payload.options
    ]


class QuestionBankService:
    """Manages course-scoped multiple-choice questions for instructors/admins."""

    def __init__(
        self,
        *,
        access_policy: CourseAccessPolicy,
        question_repository: QuestionRepository,
        learning_outcome_repository: LearningOutcomeRepository,
        transaction_manager: TransactionManager,
    ) -> None:
        self._access = access_policy
        self._questions = question_repository
        self._outcomes = learning_outcome_repository
        self._tx = transaction_manager

    def list_questions(
        self,
        *,
        user: User,
        course_id: int,
        learning_outcome_id: int | None = None,
        difficulty_level: str | None = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[QuestionInstructorResponse]:
        """List instructor-facing questions for a course (authorized managers only)."""
        self._access.check_manage_access(user, course_id)
        if limit < 1 or limit > 100:
            raise PaginationValidationError("limit must be between 1 and 100.")
        if offset < 0:
            raise PaginationValidationError("offset must be >= 0.")

        if learning_outcome_id is not None:
            outcome = self._outcomes.get_by_id_for_course(
                learning_outcome_id, course_id
            )
            if outcome is None:
                raise CrossCourseReferenceError(
                    "Learning outcome does not belong to the specified course."
                )

        page = self._questions.list_by_course(
            course_id,
            learning_outcome_id=learning_outcome_id,
            difficulty_level=difficulty_level,
            active_only=not include_archived,
            limit=limit,
            offset=offset,
        )
        options_by_qid = self._questions.list_options_for_questions(
            [q.id for q in page]
        )
        return [
            QuestionInstructorResponse.from_models(q, options_by_qid.get(q.id, []))
            for q in page
        ]

    def get_question(
        self,
        *,
        user: User,
        course_id: int,
        question_id: int,
    ) -> QuestionInstructorResponse:
        """Return a single instructor-facing question scoped to `course_id`."""
        self._access.check_manage_access(user, course_id)
        question = self._questions.get_by_id_for_course(question_id, course_id)
        if question is None:
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)
        options = self._questions.list_options(question.id)
        return QuestionInstructorResponse.from_models(question, options)

    def create_question(
        self,
        *,
        user: User,
        course_id: int,
        payload: QuestionCreateRequest,
    ) -> QuestionInstructorResponse:
        """Atomically create a multiple-choice question and its 4 options."""
        self._access.check_manage_access(user, course_id)

        with self._tx.begin():
            outcome = self._outcomes.get_by_id_for_course(
                payload.learning_outcome_id, course_id
            )
            if outcome is None:
                raise CrossCourseReferenceError(
                    "Learning outcome does not belong to the specified course."
                )
            question, options = self._questions.create_with_options(
                course_id=course_id,
                learning_outcome_id=payload.learning_outcome_id,
                question_text=payload.question_text,
                options=_to_option_drafts(payload),
                question_type=QuestionType.MULTIPLE_CHOICE.value,
                difficulty_level=payload.difficulty_level.value,
                points=payload.points,
                created_by=user.id,
            )
            response = QuestionInstructorResponse.from_models(question, options)
        return response

    def update_question(
        self,
        *,
        user: User,
        course_id: int,
        question_id: int,
        payload: QuestionUpdateRequest,
    ) -> QuestionUpdateResponse:
        """Update an unused question in-place, or archive and version a used one."""
        self._access.check_manage_access(user, course_id)

        with self._tx.begin():
            outcome = self._outcomes.get_by_id_for_course(
                payload.learning_outcome_id, course_id
            )
            if outcome is None:
                raise CrossCourseReferenceError(
                    "Learning outcome does not belong to the specified course."
                )
            try:
                question, options, was_versioned = self._questions.update_or_version(
                    course_id=course_id,
                    question_id=question_id,
                    learning_outcome_id=payload.learning_outcome_id,
                    question_text=payload.question_text,
                    options=_to_option_drafts(payload),
                    question_type=QuestionType.MULTIPLE_CHOICE.value,
                    difficulty_level=payload.difficulty_level.value,
                    points=payload.points,
                    updated_by=user.id,
                )
            except QuestionNotFoundError as error:
                raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE) from error
            response = QuestionUpdateResponse(
                question=QuestionInstructorResponse.from_models(question, options),
                was_versioned=was_versioned,
                previous_question_id=question_id if was_versioned else None,
            )

        return response

    def delete_question(
        self,
        *,
        user: User,
        course_id: int,
        question_id: int,
    ) -> QuestionDeleteResponse:
        """Archive a question referenced by any assessment, or hard-delete if unused."""
        self._access.check_manage_access(user, course_id)

        with self._tx.begin():
            try:
                archived = self._questions.delete_or_archive(
                    course_id=course_id,
                    question_id=question_id,
                )
            except QuestionNotFoundError as error:
                raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE) from error

        return QuestionDeleteResponse(
            question_id=question_id,
            archived=archived,
        )
