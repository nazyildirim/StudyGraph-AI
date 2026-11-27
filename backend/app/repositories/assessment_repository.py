"""Assessment, StudentAssessment, and StudentResponse persistence (Issue #7).

Transaction convention (caller-owned Unit-of-Work):
- Mutating methods flush within SAVEPOINTs and NEVER call `session.commit()`.
- Lock ordering:
  - Tier 3 (`student_assessments`): `get_attempt_for_student(..., for_update=True)`
    and `save_responses_and_complete_attempt` lock the attempt row via
    `SELECT ... FOR UPDATE`.
  - Tier 4 (`questions`): `create_assessment_with_questions` locks target
    question rows in ascending `id` order via `SELECT ... FOR UPDATE`, matching
    `QuestionRepository` so concurrent edits/archives and exam assignments are
    strictly serialized without deadlocks.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.assessment import Assessment, AssessmentType
from app.models.assessment_question import AssessmentQuestion
from app.models.question import Question
from app.models.student_assessment import StudentAssessment, StudentAssessmentStatus
from app.models.student_response import StudentResponse
from app.repositories.errors import (
    AssessmentNotFoundError,
    AttemptAlreadyFinalizedError,
    AttemptNotFoundError,
    CrossCourseReferenceError,
    DuplicateResponseError,
    InvalidResponseError,
    QuestionArchivedError,
    RelatedRecordNotFoundError,
    is_foreign_key_violation,
    is_unique_violation,
)

RESPONSE_ATTEMPT_QUESTION_UNIQUE = "uq_student_responses_attempt_question"


@dataclass(frozen=True, slots=True)
class StudentResponseDraft:
    """Server-graded response ready for atomic persistence."""

    question_id: int
    selected_option_id: int | None
    is_correct: bool
    score_earned: float


class AssessmentRepository(Protocol):
    """Repository contract for assessments, attempts, responses, and seen lineages."""

    def create_assessment_with_questions(
        self,
        *,
        course_id: int,
        title: str,
        assessment_type: str,
        question_ids: Sequence[int],
        description: str | None = None,
        time_limit_minutes: int | None = None,
        created_by: int | None = None,
    ) -> tuple[Assessment, list[AssessmentQuestion]]: ...

    def get_assessment_for_course(
        self, assessment_id: int, course_id: int
    ) -> Assessment | None: ...

    def list_assessments_by_ids(
        self, assessment_ids: Sequence[int]
    ) -> dict[int, Assessment]: ...

    def list_assessment_questions(
        self, assessment_id: int, *, course_id: int | None = None
    ) -> list[AssessmentQuestion]: ...

    def create_attempt(
        self, *, student_id: int, assessment_id: int, course_id: int
    ) -> StudentAssessment: ...

    def get_attempt_for_student(
        self,
        *,
        attempt_id: int,
        student_id: int,
        course_id: int | None = None,
        for_update: bool = False,
    ) -> StudentAssessment | None: ...

    def list_attempts_for_student(
        self,
        *,
        student_id: int,
        course_id: int,
        assessment_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[StudentAssessment]: ...

    def list_responses_for_attempt(
        self, *, attempt_id: int, student_id: int
    ) -> list[StudentResponse]: ...

    def save_responses_and_complete_attempt(
        self,
        *,
        attempt_id: int,
        student_id: int,
        course_id: int,
        responses: Sequence[StudentResponseDraft],
        score: float,
        completed_at: datetime | None = None,
    ) -> tuple[StudentAssessment, list[StudentResponse]]: ...

    def get_seen_question_lineage_ids(
        self, *, student_id: int, course_id: int
    ) -> set[int]: ...


class SqlAlchemyAssessmentRepository:
    """SQLAlchemy 2.0 implementation of AssessmentRepository."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_assessment_with_questions(
        self,
        *,
        course_id: int,
        title: str,
        assessment_type: str,
        question_ids: Sequence[int],
        description: str | None = None,
        time_limit_minutes: int | None = None,
        created_by: int | None = None,
    ) -> tuple[Assessment, list[AssessmentQuestion]]:
        if not title or not title.strip():
            raise ValueError("Assessment title cannot be empty.")
        if assessment_type not in {item.value for item in AssessmentType}:
            raise ValueError(f"Unsupported assessment_type: {assessment_type!r}.")
        if time_limit_minutes is not None and time_limit_minutes <= 0:
            raise ValueError("time_limit_minutes must be positive when provided.")
        if not question_ids:
            raise ValueError("An assessment must include at least one question.")
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("Duplicate question IDs are not allowed in an assessment.")

        # Tier 4 lock: lock target questions in deterministic ascending ID order.
        ordered_ids = sorted(question_ids)
        locked_questions = list(
            self._session.execute(
                select(Question)
                .where(Question.id.in_(ordered_ids))
                .order_by(Question.id.asc())
                .with_for_update()
            ).scalars()
        )
        by_id = {q.id: q for q in locked_questions}
        if len(by_id) != len(ordered_ids):
            raise RelatedRecordNotFoundError("question")

        for qid in ordered_ids:
            question = by_id[qid]
            if question.course_id != course_id:
                raise CrossCourseReferenceError(
                    f"Question {qid} does not belong to course {course_id}."
                )
            if not question.is_active:
                raise QuestionArchivedError(
                    f"Question {qid} is archived and cannot be assigned to a new assessment."
                )

        assessment = Assessment(
            course_id=course_id,
            title=title.strip(),
            description=description,
            assessment_type=assessment_type,
            time_limit_minutes=time_limit_minutes,
            created_by=created_by,
        )
        aq_rows: list[AssessmentQuestion] = []
        try:
            with self._session.begin_nested():
                self._session.add(assessment)
                self._session.flush()
                aq_rows = [
                    AssessmentQuestion(
                        assessment_id=assessment.id,
                        question_id=qid,
                        course_id=course_id,
                        order_index=index,
                    )
                    for index, qid in enumerate(question_ids)
                ]
                self._session.add_all(aq_rows)
                self._session.flush()
        except IntegrityError as error:
            if is_foreign_key_violation(error):
                raise RelatedRecordNotFoundError("course, question, or user") from error
            raise
        return assessment, aq_rows

    def get_assessment_for_course(
        self, assessment_id: int, course_id: int
    ) -> Assessment | None:
        return self._session.execute(
            select(Assessment).where(
                Assessment.id == assessment_id,
                Assessment.course_id == course_id,
            )
        ).scalar_one_or_none()

    def list_assessments_by_ids(
        self, assessment_ids: Sequence[int]
    ) -> dict[int, Assessment]:
        if not assessment_ids:
            return {}
        rows = self._session.execute(
            select(Assessment).where(Assessment.id.in_(set(assessment_ids)))
        ).scalars()
        return {row.id: row for row in rows}

    def list_assessment_questions(
        self, assessment_id: int, *, course_id: int | None = None
    ) -> list[AssessmentQuestion]:
        stmt = select(AssessmentQuestion).where(
            AssessmentQuestion.assessment_id == assessment_id
        )
        if course_id is not None:
            stmt = stmt.where(AssessmentQuestion.course_id == course_id)
        stmt = stmt.order_by(
            AssessmentQuestion.order_index.asc(),
            AssessmentQuestion.id.asc(),
        )
        return list(self._session.execute(stmt).scalars())

    def create_attempt(
        self, *, student_id: int, assessment_id: int, course_id: int
    ) -> StudentAssessment:
        assessment = self.get_assessment_for_course(assessment_id, course_id)
        if assessment is None:
            raise AssessmentNotFoundError(
                f"Assessment {assessment_id} not found in course {course_id}."
            )
        attempt = StudentAssessment(
            student_id=student_id,
            assessment_id=assessment.id,
            status=StudentAssessmentStatus.IN_PROGRESS.value,
        )
        try:
            with self._session.begin_nested():
                self._session.add(attempt)
                self._session.flush()
        except IntegrityError as error:
            if is_foreign_key_violation(error):
                raise RelatedRecordNotFoundError("student or assessment") from error
            raise
        return attempt

    def get_attempt_for_student(
        self,
        *,
        attempt_id: int,
        student_id: int,
        course_id: int | None = None,
        for_update: bool = False,
    ) -> StudentAssessment | None:
        stmt = select(StudentAssessment).where(
            StudentAssessment.id == attempt_id,
            StudentAssessment.student_id == student_id,
        )
        if course_id is not None:
            stmt = stmt.join(
                Assessment, Assessment.id == StudentAssessment.assessment_id
            ).where(Assessment.course_id == course_id)
        if for_update:
            # Lock only the student_assessments row (Tier 3) and force refresh
            # from PostgreSQL so identity-map cache can never mask concurrent updates.
            stmt = stmt.with_for_update(of=StudentAssessment).execution_options(
                populate_existing=True
            )
        return self._session.execute(stmt).scalar_one_or_none()

    def list_attempts_for_student(
        self,
        *,
        student_id: int,
        course_id: int,
        assessment_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[StudentAssessment]:
        stmt = (
            select(StudentAssessment)
            .join(Assessment, Assessment.id == StudentAssessment.assessment_id)
            .where(
                StudentAssessment.student_id == student_id,
                Assessment.course_id == course_id,
            )
        )
        if assessment_type is not None:
            stmt = stmt.where(Assessment.assessment_type == assessment_type)
        if status is not None:
            stmt = stmt.where(StudentAssessment.status == status)
        stmt = (
            stmt.order_by(
                StudentAssessment.started_at.desc(),
                StudentAssessment.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(self._session.execute(stmt).scalars())

    def list_responses_for_attempt(
        self, *, attempt_id: int, student_id: int
    ) -> list[StudentResponse]:
        return list(
            self._session.execute(
                select(StudentResponse)
                .join(
                    StudentAssessment,
                    StudentAssessment.id == StudentResponse.student_assessment_id,
                )
                .where(
                    StudentResponse.student_assessment_id == attempt_id,
                    StudentAssessment.student_id == student_id,
                )
                .order_by(StudentResponse.id.asc())
            ).scalars()
        )

    def save_responses_and_complete_attempt(
        self,
        *,
        attempt_id: int,
        student_id: int,
        course_id: int,
        responses: Sequence[StudentResponseDraft],
        score: float,
        completed_at: datetime | None = None,
    ) -> tuple[StudentAssessment, list[StudentResponse]]:
        if isinstance(score, bool) or not 0.0 <= score <= 100.0:
            raise ValueError("Attempt score must be between 0 and 100.")

        # Tier 3 lock: serialize concurrent submissions of the same attempt.
        attempt = self.get_attempt_for_student(
            attempt_id=attempt_id,
            student_id=student_id,
            course_id=course_id,
            for_update=True,
        )
        if attempt is None:
            raise AttemptNotFoundError(
                f"Attempt {attempt_id} not found for student {student_id} in course {course_id}."
            )
        if attempt.status != StudentAssessmentStatus.IN_PROGRESS.value:
            raise AttemptAlreadyFinalizedError(
                f"Attempt {attempt_id} is already {attempt.status}."
            )

        seen_qids: set[int] = set()
        for item in responses:
            if item.question_id in seen_qids:
                raise DuplicateResponseError(
                    f"Duplicate response for question {item.question_id}."
                )
            seen_qids.add(item.question_id)

        finished_at = completed_at or datetime.now(timezone.utc)
        rows = [
            StudentResponse(
                student_assessment_id=attempt.id,
                assessment_id=attempt.assessment_id,
                question_id=item.question_id,
                selected_option_id=item.selected_option_id,
                is_correct=item.is_correct,
                score_earned=item.score_earned,
                answered_at=finished_at,
            )
            for item in responses
        ]
        try:
            with self._session.begin_nested():
                self._session.add_all(rows)
                attempt.status = StudentAssessmentStatus.COMPLETED.value
                attempt.score = score
                attempt.completed_at = finished_at
                self._session.flush()
        except IntegrityError as error:
            if is_unique_violation(error, RESPONSE_ATTEMPT_QUESTION_UNIQUE):
                raise DuplicateResponseError(
                    "A response for this question already exists in this attempt."
                ) from error
            if is_foreign_key_violation(error):
                raise InvalidResponseError(
                    "Response references an unassigned question or mismatched option."
                ) from error
            raise
        return attempt, rows

    def get_seen_question_lineage_ids(
        self, *, student_id: int, course_id: int
    ) -> set[int]:
        """Return canonical lineage IDs (`COALESCE(root_question_id, id)`) of all
        questions ever assigned to any assessment attempt started by `student_id`
        in `course_id` (including in-progress/abandoned attempts without responses).
        """
        lineage_expr = func.coalesce(Question.root_question_id, Question.id)
        rows = self._session.execute(
            select(lineage_expr)
            .distinct()
            .select_from(StudentAssessment)
            .join(Assessment, Assessment.id == StudentAssessment.assessment_id)
            .join(
                AssessmentQuestion,
                AssessmentQuestion.assessment_id == Assessment.id,
            )
            .join(Question, Question.id == AssessmentQuestion.question_id)
            .where(
                StudentAssessment.student_id == student_id,
                Assessment.course_id == course_id,
            )
        ).scalars()
        return set(rows)
