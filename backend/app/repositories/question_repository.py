"""Question and QuestionOption persistence with immutable versioning (Issue #7).

Transaction convention (caller-owned Unit-of-Work):
- Mutating methods flush within SAVEPOINTs and NEVER call `session.commit()`.
- Lock ordering (Tier 4): mutating operations lock the entire question lineage
  (`id = root_id OR root_question_id = root_id`) ordered by `id ASC` via
  `SELECT ... FOR UPDATE`, matching the lock order used by
  `AssessmentRepository.create_assessment_with_questions` so concurrent edits,
  deletes, and exam assignments cannot deadlock or violate immutability.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.assessment_question import AssessmentQuestion
from app.models.learning_outcome_record import LearningOutcomeRecord
from app.models.question import DifficultyLevel, Question, QuestionType
from app.models.question_option import QuestionOption
from app.repositories.errors import (
    CrossCourseReferenceError,
    InvalidQuestionOptionsError,
    QuestionArchivedError,
    QuestionNotFoundError,
    RelatedRecordNotFoundError,
    is_foreign_key_violation,
)


@dataclass(frozen=True, slots=True)
class QuestionOptionDraft:
    """Validated input representation of a question answer option."""

    option_text: str
    is_correct: bool
    order_index: int


def validate_question_options(options: Sequence[QuestionOptionDraft]) -> None:
    """Enforce >= 2 options, unique non-negative order_index, and exactly 1 correct."""
    if len(options) < 2:
        raise InvalidQuestionOptionsError("A question must have at least 2 options.")

    seen_indices: set[int] = set()
    correct_count = 0
    for option in options:
        if not option.option_text or not option.option_text.strip():
            raise InvalidQuestionOptionsError("Option text cannot be empty.")
        if option.order_index < 0:
            raise InvalidQuestionOptionsError("Option order_index must be non-negative.")
        if option.order_index in seen_indices:
            raise InvalidQuestionOptionsError(
                f"Duplicate option order_index: {option.order_index}."
            )
        seen_indices.add(option.order_index)
        if option.is_correct:
            correct_count += 1

    if correct_count != 1:
        raise InvalidQuestionOptionsError(
            "A question must have exactly one correct option."
        )


def _validate_question_metadata(
    *,
    question_text: str,
    question_type: str,
    difficulty_level: str,
    points: float,
) -> None:
    if not question_text or not question_text.strip():
        raise ValueError("Question text cannot be empty.")
    if question_type not in {item.value for item in QuestionType}:
        raise ValueError(f"Unsupported question_type: {question_type!r}.")
    if difficulty_level not in {item.value for item in DifficultyLevel}:
        raise ValueError(f"Unsupported difficulty_level: {difficulty_level!r}.")
    if isinstance(points, bool) or points <= 0:
        raise ValueError("Question points must be positive.")


class QuestionRepository(Protocol):
    """Repository contract for question bank persistence and versioning."""

    def get_by_id(self, question_id: int) -> Question | None: ...

    def get_by_id_for_course(
        self, question_id: int, course_id: int
    ) -> Question | None: ...

    def list_by_ids(self, question_ids: Sequence[int]) -> list[Question]: ...

    def list_options(self, question_id: int) -> list[QuestionOption]: ...

    def list_options_for_questions(
        self, question_ids: Sequence[int]
    ) -> dict[int, list[QuestionOption]]: ...

    def list_by_course(
        self,
        course_id: int,
        *,
        learning_outcome_id: int | None = None,
        difficulty_level: str | None = None,
        active_only: bool = True,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Question]: ...

    def list_active_pool(
        self,
        course_id: int,
        *,
        learning_outcome_ids: Sequence[int] | None = None,
        difficulty_level: str | None = None,
    ) -> list[Question]: ...

    def is_used_in_any_assessment(self, question_id: int) -> bool: ...

    def create_with_options(
        self,
        *,
        course_id: int,
        learning_outcome_id: int,
        question_text: str,
        options: Sequence[QuestionOptionDraft],
        question_type: str = QuestionType.MULTIPLE_CHOICE.value,
        difficulty_level: str = DifficultyLevel.MEDIUM.value,
        points: float = 1.0,
        created_by: int | None = None,
    ) -> tuple[Question, list[QuestionOption]]: ...

    def update_or_version(
        self,
        *,
        course_id: int,
        question_id: int,
        learning_outcome_id: int,
        question_text: str,
        options: Sequence[QuestionOptionDraft],
        question_type: str = QuestionType.MULTIPLE_CHOICE.value,
        difficulty_level: str = DifficultyLevel.MEDIUM.value,
        points: float = 1.0,
        updated_by: int | None = None,
    ) -> tuple[Question, list[QuestionOption], bool]: ...

    def delete_or_archive(self, *, course_id: int, question_id: int) -> bool: ...


class SqlAlchemyQuestionRepository:
    """SQLAlchemy 2.0 implementation of QuestionRepository."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, question_id: int) -> Question | None:
        return self._session.get(Question, question_id)

    def get_by_id_for_course(
        self, question_id: int, course_id: int
    ) -> Question | None:
        return self._session.execute(
            select(Question).where(
                Question.id == question_id,
                Question.course_id == course_id,
            )
        ).scalar_one_or_none()

    def list_by_ids(self, question_ids: Sequence[int]) -> list[Question]:
        if not question_ids:
            return []
        return list(
            self._session.execute(
                select(Question)
                .where(Question.id.in_(set(question_ids)))
                .order_by(Question.id.asc())
            ).scalars()
        )

    def list_options(self, question_id: int) -> list[QuestionOption]:
        return list(
            self._session.execute(
                select(QuestionOption)
                .where(QuestionOption.question_id == question_id)
                .order_by(QuestionOption.order_index.asc(), QuestionOption.id.asc())
            ).scalars()
        )

    def list_options_for_questions(
        self, question_ids: Sequence[int]
    ) -> dict[int, list[QuestionOption]]:
        if not question_ids:
            return {}
        rows = self._session.execute(
            select(QuestionOption)
            .where(QuestionOption.question_id.in_(set(question_ids)))
            .order_by(
                QuestionOption.question_id.asc(),
                QuestionOption.order_index.asc(),
                QuestionOption.id.asc(),
            )
        ).scalars()
        grouped: dict[int, list[QuestionOption]] = {qid: [] for qid in question_ids}
        for row in rows:
            grouped.setdefault(row.question_id, []).append(row)
        return grouped

    def list_by_course(
        self,
        course_id: int,
        *,
        learning_outcome_id: int | None = None,
        difficulty_level: str | None = None,
        active_only: bool = True,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Question]:
        stmt = select(Question).where(Question.course_id == course_id)
        if learning_outcome_id is not None:
            stmt = stmt.where(Question.learning_outcome_id == learning_outcome_id)
        if difficulty_level is not None:
            stmt = stmt.where(Question.difficulty_level == difficulty_level)
        if active_only:
            stmt = stmt.where(Question.is_active.is_(True))
        stmt = stmt.order_by(Question.id.asc())
        if offset > 0:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self._session.execute(stmt).scalars())

    def list_active_pool(
        self,
        course_id: int,
        *,
        learning_outcome_ids: Sequence[int] | None = None,
        difficulty_level: str | None = None,
    ) -> list[Question]:
        stmt = select(Question).where(
            Question.course_id == course_id,
            Question.is_active.is_(True),
        )
        if learning_outcome_ids is not None:
            ids = set(learning_outcome_ids)
            if not ids:
                return []
            stmt = stmt.where(Question.learning_outcome_id.in_(ids))
        if difficulty_level is not None:
            stmt = stmt.where(Question.difficulty_level == difficulty_level)
        stmt = stmt.order_by(Question.id.asc())
        return list(self._session.execute(stmt).scalars())

    def is_used_in_any_assessment(self, question_id: int) -> bool:
        found = self._session.execute(
            select(AssessmentQuestion.id)
            .where(AssessmentQuestion.question_id == question_id)
            .limit(1)
        ).scalar_one_or_none()
        return found is not None

    def _assert_outcome_in_course(
        self, *, course_id: int, learning_outcome_id: int
    ) -> None:
        outcome = self._session.execute(
            select(LearningOutcomeRecord.id).where(
                LearningOutcomeRecord.id == learning_outcome_id,
                LearningOutcomeRecord.course_id == course_id,
            )
        ).scalar_one_or_none()
        if outcome is None:
            raise CrossCourseReferenceError(
                "Learning outcome does not belong to the specified course."
            )

    def _lock_question_lineage(
        self, *, course_id: int, question_id: int
    ) -> tuple[Question, list[Question], int]:
        """Tier 4 lock: lock the target question and all rows in its lineage."""
        # First lock the target row to read its immutable lineage root safely.
        target = self._session.execute(
            select(Question)
            .where(Question.id == question_id, Question.course_id == course_id)
            .with_for_update()
        ).scalar_one_or_none()
        if target is None:
            raise QuestionNotFoundError(f"Question {question_id} not found in course {course_id}.")

        root_id = target.root_question_id if target.root_question_id is not None else target.id
        lineage = list(
            self._session.execute(
                select(Question)
                .where(
                    or_(Question.id == root_id, Question.root_question_id == root_id)
                )
                .order_by(Question.id.asc())
                .with_for_update()
            ).scalars()
        )
        # Re-read target from the locked lineage list and verify same-course lineage.
        for item in lineage:
            if item.course_id != course_id:
                raise CrossCourseReferenceError(
                    "Question lineage crosses course boundaries."
                )
        return target, lineage, root_id

    def create_with_options(
        self,
        *,
        course_id: int,
        learning_outcome_id: int,
        question_text: str,
        options: Sequence[QuestionOptionDraft],
        question_type: str = QuestionType.MULTIPLE_CHOICE.value,
        difficulty_level: str = DifficultyLevel.MEDIUM.value,
        points: float = 1.0,
        created_by: int | None = None,
    ) -> tuple[Question, list[QuestionOption]]:
        _validate_question_metadata(
            question_text=question_text,
            question_type=question_type,
            difficulty_level=difficulty_level,
            points=points,
        )
        validate_question_options(options)
        self._assert_outcome_in_course(
            course_id=course_id, learning_outcome_id=learning_outcome_id
        )

        question = Question(
            course_id=course_id,
            learning_outcome_id=learning_outcome_id,
            question_text=question_text.strip(),
            question_type=question_type,
            difficulty_level=difficulty_level,
            points=points,
            created_by=created_by,
        )
        option_rows: list[QuestionOption] = []
        try:
            with self._session.begin_nested():
                self._session.add(question)
                self._session.flush()
                option_rows = [
                    QuestionOption(
                        question_id=question.id,
                        option_text=opt.option_text.strip(),
                        is_correct=opt.is_correct,
                        order_index=opt.order_index,
                    )
                    for opt in sorted(options, key=lambda item: item.order_index)
                ]
                self._session.add_all(option_rows)
                self._session.flush()
        except IntegrityError as error:
            if is_foreign_key_violation(error):
                raise RelatedRecordNotFoundError("course, outcome, or user") from error
            raise
        return question, option_rows

    def update_or_version(
        self,
        *,
        course_id: int,
        question_id: int,
        learning_outcome_id: int,
        question_text: str,
        options: Sequence[QuestionOptionDraft],
        question_type: str = QuestionType.MULTIPLE_CHOICE.value,
        difficulty_level: str = DifficultyLevel.MEDIUM.value,
        points: float = 1.0,
        updated_by: int | None = None,
    ) -> tuple[Question, list[QuestionOption], bool]:
        """Update an unused question in-place, or archive and create a new version.

        Returns `(question, options, was_versioned)`.
        A question included in ANY `assessment_questions` row is immutable and
        will be archived (`is_active = False`, `archived_at = now`) while a new
        version (`version_number + 1`) is created under the same `root_question_id`.
        """
        _validate_question_metadata(
            question_text=question_text,
            question_type=question_type,
            difficulty_level=difficulty_level,
            points=points,
        )
        validate_question_options(options)
        self._assert_outcome_in_course(
            course_id=course_id, learning_outcome_id=learning_outcome_id
        )

        target, lineage, root_id = self._lock_question_lineage(
            course_id=course_id, question_id=question_id
        )
        if not target.is_active:
            raise QuestionArchivedError(
                f"Question {question_id} is archived and cannot be edited."
            )

        # Ensure no other active version exists in this lineage.
        other_active = [
            item for item in lineage if item.id != target.id and item.is_active
        ]
        if other_active:
            raise QuestionArchivedError(
                "Another active version already exists in this question lineage."
            )

        sorted_options = sorted(options, key=lambda item: item.order_index)
        if not self.is_used_in_any_assessment(target.id):
            # Unused question: safe to update in-place atomically.
            with self._session.begin_nested():
                target.learning_outcome_id = learning_outcome_id
                target.question_text = question_text.strip()
                target.question_type = question_type
                target.difficulty_level = difficulty_level
                target.points = points
                self._session.execute(
                    delete(QuestionOption).where(
                        QuestionOption.question_id == target.id
                    )
                )
                self._session.flush()
                new_options = [
                    QuestionOption(
                        question_id=target.id,
                        option_text=opt.option_text.strip(),
                        is_correct=opt.is_correct,
                        order_index=opt.order_index,
                    )
                    for opt in sorted_options
                ]
                self._session.add_all(new_options)
                self._session.flush()
            return target, new_options, False

        # Used in at least one assessment: archive old version and insert new version.
        now = datetime.now(timezone.utc)
        next_version_number = max(item.version_number for item in lineage) + 1
        with self._session.begin_nested():
            target.is_active = False
            target.archived_at = now
            self._session.flush()

            new_question = Question(
                course_id=course_id,
                learning_outcome_id=learning_outcome_id,
                question_text=question_text.strip(),
                question_type=question_type,
                difficulty_level=difficulty_level,
                points=points,
                is_active=True,
                archived_at=None,
                version_number=next_version_number,
                root_question_id=root_id,
                previous_version_id=target.id,
                created_by=updated_by if updated_by is not None else target.created_by,
            )
            self._session.add(new_question)
            self._session.flush()
            new_options = [
                QuestionOption(
                    question_id=new_question.id,
                    option_text=opt.option_text.strip(),
                    is_correct=opt.is_correct,
                    order_index=opt.order_index,
                )
                for opt in sorted_options
            ]
            self._session.add_all(new_options)
            self._session.flush()
        return new_question, new_options, True

    def delete_or_archive(self, *, course_id: int, question_id: int) -> bool:
        """Archive if referenced by any assessment or child version; hard-delete otherwise.

        Returns `True` when archived (soft-deleted), `False` when physically deleted.
        """
        target, lineage, _ = self._lock_question_lineage(
            course_id=course_id, question_id=question_id
        )
        has_dependents = self.is_used_in_any_assessment(target.id) or any(
            item.root_question_id == target.id or item.previous_version_id == target.id
            for item in lineage
            if item.id != target.id
        )
        if has_dependents:
            if target.is_active:
                with self._session.begin_nested():
                    target.is_active = False
                    target.archived_at = datetime.now(timezone.utc)
                    self._session.flush()
            return True

        with self._session.begin_nested():
            self._session.delete(target)
            self._session.flush()
        return False
