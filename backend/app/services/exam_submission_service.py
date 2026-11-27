"""Application service and pure grading engine for Exam Submissions (Issue #7).

Architectural principles:
- SRP: Pure, DB-independent server-side grading (`grade_exam_submission`) is
  separated from transaction/authorization orchestration (`ExamSubmissionService`).
- DIP: Depends on repository Protocols, `CourseAccessPolicy`, and
  `TransactionManager`. Zero FastAPI/HTTP dependencies.
- Lock ordering:
  1. Tier 2 (`MasteryRepository.acquire_student_course_lock`) serializes
     concurrent exam submissions for `(student_id, course_id)`.
  2. Tier 3 (`AssessmentRepository.get_attempt_for_student(..., for_update=True)`)
     locks the `student_assessments` row with `populate_existing=True` so stale
     identity-map state can never bypass `AttemptAlreadyFinalizedError`.
- Phase 6 readiness: All writes happen in a single caller-owned transaction
  without premature commits so `LearningAnalysisService` + `MasteryRepository`
  persistence can join the exact same atomic transaction in Phase 6.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import math

from app.authorization.course_access_policy import CourseAccessPolicy
from app.authorization.ownership import (
    RESOURCE_NOT_FOUND_MESSAGE,
    ResourceNotFoundError,
    RoleAuthorizationError,
    parse_user_role,
)
from app.authorization.roles import Role
from app.models.question import Question
from app.models.question_option import QuestionOption
from app.models.student_assessment import StudentAssessmentStatus
from app.models.user import User
from app.repositories.assessment_repository import (
    AssessmentRepository,
    StudentResponseDraft,
)
from app.repositories.errors import (
    AttemptAlreadyFinalizedError,
    DuplicateResponseError,
    InvalidResponseError,
    PaginationValidationError,
)
from app.repositories.mastery_repository import MasteryRepository
from app.repositories.question_repository import QuestionRepository
from app.schemas.exam import (
    ExamHistoryItemResponse,
    ExamMasterySummaryResponse,
    ExamQuestionResult,
    ExamResultResponse,
    ExamSubmitRequest,
    StudentAnswerRequest,
)
from app.services.mastery_integration import MasteryIntegrator
from app.services.question_bank_service import TransactionManager

MAX_HISTORY_LIMIT = 100


class AttemptNotCompletedError(Exception):
    """Raised when exam results are requested for an incomplete attempt."""


@dataclass(frozen=True, slots=True)
class GradedExam:
    """Pure output of server-side exam grading."""

    response_drafts: tuple[StudentResponseDraft, ...]
    question_results: tuple[ExamQuestionResult, ...]
    total_questions: int
    correct_count: int
    incorrect_count: int
    unanswered_count: int
    earned_points: float
    total_possible_points: float
    score: float


def _to_decimal_points(value: float) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Question points must be a numeric value.")
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Question points must be finite and positive.")
    return Decimal(str(value))


def grade_exam_submission(
    *,
    assigned_questions: Sequence[tuple[int, Question]],
    options_by_question_id: Mapping[int, Sequence[QuestionOption]],
    submitted_answers: Sequence[StudentAnswerRequest],
) -> GradedExam:
    """Grade student answers purely against assigned question versions and DB options.

    Rules:
    - Every submitted `question_id` must belong to `assigned_questions`.
    - Duplicate `question_id` entries are rejected.
    - When `selected_option_id` is provided, it must belong to that exact question.
    - Omitted questions or `selected_option_id=None` are graded as unanswered
      (`is_correct=False`, `score_earned=0.0`).
    - Correct answers earn `question.points`; wrong/unanswered earn `0.0`.
    - `score = (earned_points / total_possible_points) * 100` rounded to 2 decimals.
    """
    if not assigned_questions:
        raise ValueError("Cannot grade an exam with zero assigned questions.")

    assigned_by_qid: dict[int, tuple[int, Question]] = {}
    for order_index, question in assigned_questions:
        assigned_by_qid[question.id] = (order_index, question)

    submitted_by_qid: dict[int, int | None] = {}
    for answer in submitted_answers:
        if answer.question_id in submitted_by_qid:
            raise DuplicateResponseError(
                f"Duplicate answer for question {answer.question_id}."
            )
        if answer.question_id not in assigned_by_qid:
            raise InvalidResponseError(
                f"Question {answer.question_id} is not assigned to this exam."
            )
        submitted_by_qid[answer.question_id] = answer.selected_option_id

    response_drafts: list[StudentResponseDraft] = []
    question_results: list[ExamQuestionResult] = []
    correct_count = 0
    incorrect_count = 0
    unanswered_count = 0
    earned_dec = Decimal("0")
    total_possible_dec = Decimal("0")

    for order_index, question in sorted(assigned_questions, key=lambda item: item[0]):
        q_points_dec = _to_decimal_points(question.points)
        total_possible_dec += q_points_dec
        selected_option_id = submitted_by_qid.get(question.id)

        if selected_option_id is None:
            is_correct = False
            score_earned_dec = Decimal("0")
            unanswered_count += 1
        else:
            valid_options = {
                opt.id: opt for opt in options_by_question_id.get(question.id, ())
            }
            chosen = valid_options.get(selected_option_id)
            if chosen is None:
                raise InvalidResponseError(
                    f"Option {selected_option_id} does not belong to question {question.id}."
                )
            if chosen.is_correct:
                is_correct = True
                score_earned_dec = q_points_dec
                correct_count += 1
                earned_dec += q_points_dec
            else:
                is_correct = False
                score_earned_dec = Decimal("0")
                incorrect_count += 1

        score_earned_float = float(score_earned_dec)
        response_drafts.append(
            StudentResponseDraft(
                question_id=question.id,
                selected_option_id=selected_option_id,
                is_correct=is_correct,
                score_earned=score_earned_float,
            )
        )
        question_results.append(
            ExamQuestionResult(
                question_id=question.id,
                learning_outcome_id=question.learning_outcome_id,
                order_index=order_index,
                selected_option_id=selected_option_id,
                is_correct=is_correct,
                score_earned=score_earned_float,
                points_possible=float(q_points_dec),
            )
        )

    raw_pct = (earned_dec * Decimal("100") / total_possible_dec).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    score = float(raw_pct)
    if not math.isfinite(score) or score < 0.0 or score > 100.0:
        raise ValueError("Computed exam score out of valid 0-100 range.")

    return GradedExam(
        response_drafts=tuple(response_drafts),
        question_results=tuple(question_results),
        total_questions=len(assigned_questions),
        correct_count=correct_count,
        incorrect_count=incorrect_count,
        unanswered_count=unanswered_count,
        earned_points=float(earned_dec),
        total_possible_points=float(total_possible_dec),
        score=score,
    )


class ExamSubmissionService:
    """Orchestrates server-side exam grading, submission, result viewing, and history."""

    def __init__(
        self,
        *,
        access_policy: CourseAccessPolicy,
        assessment_repository: AssessmentRepository,
        question_repository: QuestionRepository,
        mastery_repository: MasteryRepository,
        transaction_manager: TransactionManager,
        mastery_integrator: MasteryIntegrator | None = None,
        allow_skip_mastery_integration: bool = False,
    ) -> None:
        if mastery_integrator is None and not allow_skip_mastery_integration:
            raise ValueError(
                "mastery_integrator is required in production flows "
                "(pass allow_skip_mastery_integration=True only in isolated grading tests)."
            )
        self._access = access_policy
        self._assessments = assessment_repository
        self._questions = question_repository
        self._mastery = mastery_repository
        self._tx = transaction_manager
        self._mastery_integrator = mastery_integrator

    def _authorize_student_for_course(self, *, user: User, course_id: int) -> None:
        """Enforce active Role.STUDENT + active enrollment in an active course."""
        if user is None or not getattr(user, "is_active", False):
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)

        role = parse_user_role(user)
        if role is None:
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)
        if role is not Role.STUDENT:
            raise RoleAuthorizationError(
                "Only students may submit exams or view student exam results."
            )

        self._access.check_read_access(user, course_id)

    def submit_exam(
        self,
        *,
        user: User,
        course_id: int,
        attempt_id: int,
        payload: ExamSubmitRequest,
    ) -> ExamResultResponse:
        """Validate, grade, and persist a student's exam attempt atomically."""
        self._authorize_student_for_course(user=user, course_id=course_id)

        with self._tx.begin():
            # Tier 2 lock: serialize concurrent submissions for (student, course).
            self._mastery.acquire_student_course_lock(
                student_id=user.id, course_id=course_id
            )

            # Tier 3 lock: lock StudentAssessment with populate_existing=True.
            attempt = self._assessments.get_attempt_for_student(
                attempt_id=attempt_id,
                student_id=user.id,
                course_id=course_id,
                for_update=True,
            )
            if attempt is None:
                raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)
            if attempt.status != StudentAssessmentStatus.IN_PROGRESS.value:
                raise AttemptAlreadyFinalizedError(
                    f"Attempt {attempt_id} is already {attempt.status}."
                )

            assessment = self._assessments.get_assessment_for_course(
                attempt.assessment_id, course_id
            )
            if assessment is None:
                raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)

            assigned_rows = self._assessments.list_assessment_questions(
                assessment.id, course_id=course_id
            )
            qids = [row.question_id for row in assigned_rows]
            # Load the exact assigned question versions (including archived ones).
            questions_by_id = {q.id: q for q in self._questions.list_by_ids(qids)}
            options_by_qid = self._questions.list_options_for_questions(qids)
            assigned_pairs = [
                (row.order_index, questions_by_id[row.question_id])
                for row in assigned_rows
            ]

            graded = grade_exam_submission(
                assigned_questions=assigned_pairs,
                options_by_question_id=options_by_qid,
                submitted_answers=payload.answers,
            )

            completed_at = datetime.now(timezone.utc)
            completed_attempt, _ = self._assessments.save_responses_and_complete_attempt(
                attempt_id=attempt.id,
                student_id=user.id,
                course_id=course_id,
                responses=graded.response_drafts,
                score=graded.score,
                completed_at=completed_at,
            )

            mastery_summary: ExamMasterySummaryResponse | None = None
            if self._mastery_integrator is not None:
                evaluated_outcome_ids = {
                    item.learning_outcome_id for item in graded.question_results
                }
                mastery_summary = self._mastery_integrator.integrate_exam_submission(
                    student_id=user.id,
                    course_id=course_id,
                    evaluated_outcome_ids=evaluated_outcome_ids,
                    assessed_at=completed_at,
                )

            # Build DTO inside transaction before commit (zero post-commit lazy SELECTs).
            response = ExamResultResponse(
                attempt_id=completed_attempt.id,
                assessment_id=assessment.id,
                course_id=course_id,
                assessment_type=assessment.assessment_type,
                status=completed_attempt.status,
                started_at=completed_attempt.started_at,
                completed_at=completed_at,
                total_questions=graded.total_questions,
                correct_count=graded.correct_count,
                incorrect_count=graded.incorrect_count,
                unanswered_count=graded.unanswered_count,
                earned_points=graded.earned_points,
                total_possible_points=graded.total_possible_points,
                score=graded.score,
                results=list(graded.question_results),
                mastery_summary=mastery_summary,
            )
        return response

    def get_exam_result(
        self,
        *,
        user: User,
        course_id: int,
        attempt_id: int,
    ) -> ExamResultResponse:
        """Return the graded result of a student's own completed exam attempt."""
        self._authorize_student_for_course(user=user, course_id=course_id)

        attempt = self._assessments.get_attempt_for_student(
            attempt_id=attempt_id,
            student_id=user.id,
            course_id=course_id,
        )
        if attempt is None:
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)
        if (
            attempt.status != StudentAssessmentStatus.COMPLETED.value
            or attempt.completed_at is None
        ):
            raise AttemptNotCompletedError(
                "Exam results are only available after the attempt is completed."
            )

        assessment = self._assessments.get_assessment_for_course(
            attempt.assessment_id, course_id
        )
        if assessment is None:
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)

        assigned_rows = self._assessments.list_assessment_questions(
            assessment.id, course_id=course_id
        )
        qids = [row.question_id for row in assigned_rows]
        questions_by_id = {q.id: q for q in self._questions.list_by_ids(qids)}
        responses_by_qid = {
            resp.question_id: resp
            for resp in self._assessments.list_responses_for_attempt(
                attempt_id=attempt.id, student_id=user.id
            )
        }

        results: list[ExamQuestionResult] = []
        correct_count = 0
        incorrect_count = 0
        unanswered_count = 0
        earned_dec = Decimal("0")
        total_possible_dec = Decimal("0")

        for row in assigned_rows:
            question = questions_by_id[row.question_id]
            q_points_dec = _to_decimal_points(question.points)
            total_possible_dec += q_points_dec
            resp = responses_by_qid.get(row.question_id)

            selected_option_id = resp.selected_option_id if resp is not None else None
            is_correct = resp.is_correct if resp is not None else False
            score_earned = resp.score_earned if resp is not None else 0.0

            if selected_option_id is None:
                unanswered_count += 1
            elif is_correct:
                correct_count += 1
            else:
                incorrect_count += 1
            earned_dec += Decimal(str(score_earned))

            results.append(
                ExamQuestionResult(
                    question_id=question.id,
                    learning_outcome_id=question.learning_outcome_id,
                    order_index=row.order_index,
                    selected_option_id=selected_option_id,
                    is_correct=is_correct,
                    score_earned=score_earned,
                    points_possible=float(q_points_dec),
                )
            )

        return ExamResultResponse(
            attempt_id=attempt.id,
            assessment_id=assessment.id,
            course_id=course_id,
            assessment_type=assessment.assessment_type,
            status=attempt.status,
            started_at=attempt.started_at,
            completed_at=attempt.completed_at,
            total_questions=len(assigned_rows),
            correct_count=correct_count,
            incorrect_count=incorrect_count,
            unanswered_count=unanswered_count,
            earned_points=float(earned_dec),
            total_possible_points=float(total_possible_dec),
            score=attempt.score if attempt.score is not None else 0.0,
            results=results,
        )

    def list_exam_history(
        self,
        *,
        user: User,
        course_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ExamHistoryItemResponse]:
        """Return a student's own exam attempts in `course_id`, newest first."""
        self._authorize_student_for_course(user=user, course_id=course_id)
        if limit < 1 or limit > MAX_HISTORY_LIMIT:
            raise PaginationValidationError(
                f"limit must be between 1 and {MAX_HISTORY_LIMIT}."
            )
        if offset < 0:
            raise PaginationValidationError("offset must be >= 0.")

        attempts = self._assessments.list_attempts_for_student(
            student_id=user.id,
            course_id=course_id,
            limit=limit,
            offset=offset,
        )
        assessments_by_id = self._assessments.list_assessments_by_ids(
            [att.assessment_id for att in attempts]
        )

        items: list[ExamHistoryItemResponse] = []
        for att in attempts:
            assessment = assessments_by_id[att.assessment_id]
            is_completed = att.status == StudentAssessmentStatus.COMPLETED.value
            items.append(
                ExamHistoryItemResponse(
                    attempt_id=att.id,
                    assessment_id=att.assessment_id,
                    course_id=course_id,
                    assessment_type=assessment.assessment_type,
                    title=assessment.title,
                    status=att.status,
                    score=att.score if is_completed else None,
                    started_at=att.started_at,
                    completed_at=att.completed_at if is_completed else None,
                )
            )
        return items
