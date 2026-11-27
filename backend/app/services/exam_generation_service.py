"""Application service and pure selector for Diagnostic (Initial) Exams (Issue #7).

Architectural principles:
- SRP: Separates the pure, DB-independent round-robin question selector
  (`select_initial_exam_questions`) from orchestration (`ExamGenerationService`).
- DIP: Depends on repository Protocols, `CourseAccessPolicy`, `TransactionManager`,
  `Settings`, and an injectable RNG factory. Zero FastAPI/HTTP dependencies.
- Lock ordering:
  1. Tier 2 (`MasteryRepository.acquire_student_course_lock`) serializes
     concurrent `start_initial_exam` requests for the same `(student_id, course_id)`.
  2. Tier 4 (`AssessmentRepository.create_assessment_with_questions`) locks
     selected `questions` rows in ascending `id` order via `FOR UPDATE`.
- Lifecycle rules:
  - Only active `Role.STUDENT` users with an active course enrollment may start
    or view their own exam attempts.
  - If an `in_progress` diagnostic attempt already exists for `(student, course)`,
    the exact same attempt is returned so the student resumes where they left off.
  - If a `completed` diagnostic attempt already exists, a new diagnostic exam is
    rejected with `DiagnosticExamAlreadyCompletedError` (use retest workflow).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence, Set as AbstractSet
from dataclasses import dataclass
import json
import random

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from app.authorization.course_access_policy import CourseAccessPolicy
from app.authorization.ownership import (
    RESOURCE_NOT_FOUND_MESSAGE,
    ResourceNotFoundError,
    RoleAuthorizationError,
    parse_user_role,
)
from app.authorization.roles import Role
from app.core.config import Settings, get_settings
from app.models.assessment import Assessment, AssessmentType
from app.models.question import DifficultyLevel, Question
from app.models.student_assessment import StudentAssessment, StudentAssessmentStatus
from app.models.user import User
from app.repositories.assessment_repository import AssessmentRepository
from app.repositories.errors import CrossCourseReferenceError, QuestionArchivedError
from app.repositories.learning_outcome_repository import LearningOutcomeRepository
from app.repositories.mastery_repository import MasteryRepository
from app.repositories.question_repository import QuestionRepository
from app.schemas.exam import (
    InitialExamCreateRequest,
    RetestExamCreateRequest,
    StudentExamQuestionResponse,
    StudentExamResponse,
)
from app.services.mastery_integration import compute_live_recommendations
from app.services.question_bank_service import TransactionManager

_MAX_SELECTION_RETRIES = 2


class InsufficientQuestionsError(Exception):
    """Raised when no eligible active questions exist to build an exam."""


class DiagnosticExamAlreadyCompletedError(Exception):
    """Raised when a student already completed the course's initial diagnostic exam."""


class DiagnosticExamRequiredError(Exception):
    """Raised when a student requests a retest before completing the diagnostic exam."""


class NoEligibleOutcomesForRetestError(Exception):
    """Raised when the student has no weak, unblocked outcomes eligible for retest."""


class OutcomeNotEligibleForRetestError(Exception):
    """Raised when a specifically requested outcome is mastered, blocked, or unassessed."""


class ActiveRetestConflictError(Exception):
    """Raised when an in-progress review exam exists with different target/parameters."""


@dataclass(frozen=True, slots=True)
class InitialExamSelection:
    """Pure output of the balanced diagnostic question selection algorithm."""

    questions: tuple[Question, ...]
    requested_count: int
    actual_count: int
    uncovered_outcome_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RetestSelection:
    """Pure output of the unseen-prioritized retest question selection algorithm."""

    questions: tuple[Question, ...]
    requested_count: int
    actual_count: int
    unseen_question_count: int
    reused_question_count: int
    targeted_outcome_ids: tuple[int, ...]
    covered_outcome_ids: tuple[int, ...]
    uncovered_outcome_ids: tuple[int, ...]


def select_retest_questions(
    *,
    targeted_outcome_ids: Sequence[int],
    active_questions: Sequence[Question],
    seen_lineage_ids: AbstractSet[int],
    requested_count: int,
    difficulty: DifficultyLevel | None = None,
    rng: random.Random | None = None,
) -> RetestSelection:
    """Select up to `requested_count` retest questions prioritizing unseen lineages.

    Policy:
    - Only `is_active == True` questions belonging to `targeted_outcome_ids` are
      eligible; if `difficulty` is specified, only questions matching that exact
      `DifficultyLevel` are eligible (filter is never silently relaxed).
    - Deduplicates by canonical lineage (`COALESCE(root_question_id, id)`).
    - Pass 1 selects round-robin across `targeted_outcome_ids` from UNSEEN
      lineages (`lineage not in seen_lineage_ids`).
    - Pass 2 runs ONLY if Pass 1 yielded fewer than `requested_count`, filling
      remaining quota round-robin from SEEN lineages without repeating any
      question or lineage.
    - Guarantees `unseen_question_count + reused_question_count == actual_count`.
    """
    if requested_count < 1:
        raise ValueError("requested_count must be >= 1.")

    ordered_targets = list(dict.fromkeys(targeted_outcome_ids))
    target_set = set(ordered_targets)
    diff_value = difficulty.value if difficulty is not None else None

    best_by_lineage: dict[int, Question] = {}
    for question in active_questions:
        if not question.is_active:
            continue
        if question.learning_outcome_id not in target_set:
            continue
        if diff_value is not None and question.difficulty_level != diff_value:
            continue
        lineage = canonical_lineage_id(question)
        existing = best_by_lineage.get(lineage)
        if existing is None or (
            question.version_number,
            question.id,
        ) > (existing.version_number, existing.id):
            best_by_lineage[lineage] = question

    unseen_buckets: dict[int, list[Question]] = {oid: [] for oid in ordered_targets}
    seen_buckets: dict[int, list[Question]] = {oid: [] for oid in ordered_targets}
    for lineage, question in best_by_lineage.items():
        if lineage in seen_lineage_ids:
            seen_buckets[question.learning_outcome_id].append(question)
        else:
            unseen_buckets[question.learning_outcome_id].append(question)

    shuffler = rng if rng is not None else random.SystemRandom()
    for oid in ordered_targets:
        unseen_buckets[oid].sort(key=lambda q: q.id)
        seen_buckets[oid].sort(key=lambda q: q.id)
        shuffler.shuffle(unseen_buckets[oid])
        shuffler.shuffle(seen_buckets[oid])

    def _drain_round_robin(
        buckets: dict[int, list[Question]], limit: int
    ) -> list[Question]:
        picked: list[Question] = []
        while len(picked) < limit:
            picked_in_round = False
            for oid in ordered_targets:
                if len(picked) >= limit:
                    break
                bucket = buckets[oid]
                if bucket:
                    picked.append(bucket.pop(0))
                    picked_in_round = True
            if not picked_in_round:
                break
        return picked

    unseen_picked = _drain_round_robin(unseen_buckets, requested_count)
    remaining = requested_count - len(unseen_picked)
    reused_picked = (
        _drain_round_robin(seen_buckets, remaining) if remaining > 0 else []
    )
    selected = unseen_picked + reused_picked

    covered_set = {q.learning_outcome_id for q in selected}
    covered = tuple(oid for oid in ordered_targets if oid in covered_set)
    uncovered = tuple(oid for oid in ordered_targets if oid not in covered_set)
    return RetestSelection(
        questions=tuple(selected),
        requested_count=requested_count,
        actual_count=len(selected),
        unseen_question_count=len(unseen_picked),
        reused_question_count=len(reused_picked),
        targeted_outcome_ids=tuple(ordered_targets),
        covered_outcome_ids=covered,
        uncovered_outcome_ids=uncovered,
    )


class _DiagnosticMetadata(BaseModel):
    """Strict internal schema for persisted diagnostic exam metadata JSON."""

    model_config = ConfigDict(extra="forbid")

    requested_count: StrictInt = Field(ge=1, le=100)
    targeted_outcome_ids: list[StrictInt] = Field(default_factory=list)

    def model_post_init(self, __context: object) -> None:
        if any(oid < 1 for oid in self.targeted_outcome_ids):
            raise ValueError("targeted_outcome_ids must contain positive integers.")


class _RetestMetadata(BaseModel):
    """Strict internal schema for persisted retest exam metadata JSON."""

    model_config = ConfigDict(extra="forbid")

    requested_count: StrictInt = Field(ge=1, le=50)
    unseen_question_count: StrictInt = Field(ge=0)
    reused_question_count: StrictInt = Field(ge=0)
    targeted_outcome_ids: list[StrictInt] = Field(default_factory=list)
    requested_outcome_id: StrictInt | None = Field(default=None, ge=1)
    difficulty: DifficultyLevel | None = None

    def model_post_init(self, __context: object) -> None:
        if any(oid < 1 for oid in self.targeted_outcome_ids):
            raise ValueError("targeted_outcome_ids must contain positive integers.")


def _encode_diagnostic_metadata(
    *,
    requested_count: int,
    targeted_outcome_ids: Sequence[int],
) -> str:
    payload = _DiagnosticMetadata(
        requested_count=requested_count,
        targeted_outcome_ids=list(targeted_outcome_ids),
    )
    return payload.model_dump_json()


def _decode_diagnostic_metadata(
    description: str | None,
) -> _DiagnosticMetadata | None:
    if not description:
        return None
    try:
        parsed = json.loads(description)
        if not isinstance(parsed, dict):
            return None
        return _DiagnosticMetadata.model_validate(parsed)
    except (ValueError, TypeError, ValidationError):
        return None


def _encode_retest_metadata(
    *,
    requested_count: int,
    unseen_question_count: int,
    reused_question_count: int,
    targeted_outcome_ids: Sequence[int],
    requested_outcome_id: int | None,
    difficulty: DifficultyLevel | None,
) -> str:
    payload = _RetestMetadata(
        requested_count=requested_count,
        unseen_question_count=unseen_question_count,
        reused_question_count=reused_question_count,
        targeted_outcome_ids=list(targeted_outcome_ids),
        requested_outcome_id=requested_outcome_id,
        difficulty=difficulty,
    )
    return payload.model_dump_json()


def _decode_retest_metadata(
    description: str | None,
    *,
    actual_count: int | None = None,
) -> _RetestMetadata | None:
    if not description:
        return None
    try:
        parsed = json.loads(description)
        if not isinstance(parsed, dict):
            return None
        meta = _RetestMetadata.model_validate(parsed)
    except (ValueError, TypeError, ValidationError):
        return None
    if (
        actual_count is not None
        and meta.unseen_question_count + meta.reused_question_count != actual_count
    ):
        return None
    return meta


def canonical_lineage_id(question: Question) -> int:
    """Return canonical question lineage ID (`COALESCE(root_question_id, id)`)."""
    return (
        question.root_question_id
        if question.root_question_id is not None
        else question.id
    )


def select_initial_exam_questions(
    *,
    outcome_ids_ordered: Sequence[int],
    active_questions: Sequence[Question],
    requested_count: int,
    rng: random.Random | None = None,
) -> InitialExamSelection:
    """Select up to `requested_count` active questions via balanced round-robin.

    Policy:
    - Only `is_active == True` questions belonging to `outcome_ids_ordered` are
      eligible.
    - Deduplicates by canonical question lineage (`COALESCE(root_question_id, id)`)
      so neither the same question nor two versions of the same lineage can be
      included twice.
    - Outcomes are traversed in curriculum order (`outcome_ids_ordered`).
      When `requested_count < len(outcomes_with_questions)`, earlier outcomes
      in curriculum order are prioritized first (1 question each up to
      `requested_count`).
    - When an outcome's pool runs dry, remaining quota is filled round-robin
      from the other non-empty outcomes.
    - If total eligible unique questions < `requested_count`, returns all of
      them (`actual_count < requested_count`) without repeating any question.
    - Uncovered outcomes (0 selected questions) are reported explicitly in
      `uncovered_outcome_ids` and are never marked as failed.
    """
    if requested_count < 1:
        raise ValueError("requested_count must be >= 1.")

    ordered_outcomes = list(dict.fromkeys(outcome_ids_ordered))
    valid_outcome_set = set(ordered_outcomes)

    # Deduplicate by canonical lineage, preferring the highest version_number.
    best_by_lineage: dict[int, Question] = {}
    for question in active_questions:
        if not question.is_active:
            continue
        if question.learning_outcome_id not in valid_outcome_set:
            continue
        lineage = canonical_lineage_id(question)
        existing = best_by_lineage.get(lineage)
        if existing is None or (
            question.version_number,
            question.id,
        ) > (existing.version_number, existing.id):
            best_by_lineage[lineage] = question

    buckets: dict[int, list[Question]] = {oid: [] for oid in ordered_outcomes}
    for question in best_by_lineage.values():
        buckets[question.learning_outcome_id].append(question)

    shuffler = rng if rng is not None else random.SystemRandom()
    for oid in ordered_outcomes:
        # Sort by id before shuffle for full determinism with seeded Random.
        buckets[oid].sort(key=lambda q: q.id)
        shuffler.shuffle(buckets[oid])

    selected: list[Question] = []
    while len(selected) < requested_count:
        picked_in_round = False
        for oid in ordered_outcomes:
            if len(selected) >= requested_count:
                break
            bucket = buckets[oid]
            if bucket:
                selected.append(bucket.pop(0))
                picked_in_round = True
        if not picked_in_round:
            break

    covered_outcomes = {q.learning_outcome_id for q in selected}
    uncovered = tuple(
        oid for oid in ordered_outcomes if oid not in covered_outcomes
    )
    return InitialExamSelection(
        questions=tuple(selected),
        requested_count=requested_count,
        actual_count=len(selected),
        uncovered_outcome_ids=uncovered,
    )


class ExamGenerationService:
    """Orchestrates diagnostic exam creation and student exam attempt retrieval."""

    def __init__(
        self,
        *,
        access_policy: CourseAccessPolicy,
        assessment_repository: AssessmentRepository,
        question_repository: QuestionRepository,
        learning_outcome_repository: LearningOutcomeRepository,
        mastery_repository: MasteryRepository,
        transaction_manager: TransactionManager,
        settings: Settings | None = None,
        rng_factory: Callable[[], random.Random] | None = None,
    ) -> None:
        self._access = access_policy
        self._assessments = assessment_repository
        self._questions = question_repository
        self._outcomes = learning_outcome_repository
        self._mastery = mastery_repository
        self._tx = transaction_manager
        self._settings = settings if settings is not None else get_settings()
        self._rng_factory = rng_factory

    def _authorize_student_for_course(self, *, user: User, course_id: int) -> None:
        """Enforce active Role.STUDENT + active enrollment in an active course."""
        if user is None or not getattr(user, "is_active", False):
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)

        role = parse_user_role(user)
        if role is None:
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)
        if role is not Role.STUDENT:
            raise RoleAuthorizationError(
                "Only students may start or view student exam attempts."
            )

        self._access.check_read_access(user, course_id)

    def _build_attempt_response(
        self,
        *,
        attempt: StudentAssessment,
        course_id: int,
        assessment_type: str,
        requested_count: int,
        outcome_ids_ordered: Sequence[int],
        assessment_description: str | None = None,
        resumed: bool = False,
    ) -> StudentExamResponse:
        assigned = self._assessments.list_assessment_questions(
            attempt.assessment_id, course_id=course_id
        )
        qids = [aq.question_id for aq in assigned]
        questions_by_id = {q.id: q for q in self._questions.list_by_ids(qids)}
        options_by_qid = self._questions.list_options_for_questions(qids)

        exam_questions: list[StudentExamQuestionResponse] = []
        covered_set: set[int] = set()
        for aq in assigned:
            question = questions_by_id[aq.question_id]
            covered_set.add(question.learning_outcome_id)
            exam_questions.append(
                StudentExamQuestionResponse.from_models(
                    question=question,
                    order_index=aq.order_index,
                    options=options_by_qid.get(question.id, []),
                )
            )

        actual_count = len(exam_questions)
        if assessment_type == AssessmentType.REVIEW.value:
            retest_meta = _decode_retest_metadata(
                assessment_description, actual_count=actual_count
            )
            if retest_meta is not None:
                targeted_ids = list(retest_meta.targeted_outcome_ids)
                req_count = retest_meta.requested_count
                unseen_count: int | None = retest_meta.unseen_question_count
                reused_count: int | None = retest_meta.reused_question_count
                difficulty = (
                    retest_meta.difficulty.value
                    if retest_meta.difficulty is not None
                    else None
                )
            else:
                # Safe fallback when metadata is missing or corrupted: never fabricate
                # historical unseen/reused counts.
                targeted_ids = list(outcome_ids_ordered)
                req_count = requested_count
                unseen_count = None
                reused_count = None
                difficulty = None
        else:
            diag_meta = _decode_diagnostic_metadata(assessment_description)
            if diag_meta is not None:
                targeted_ids = list(diag_meta.targeted_outcome_ids)
                req_count = diag_meta.requested_count
            else:
                targeted_ids = list(outcome_ids_ordered)
                req_count = requested_count
            unseen_count = None
            reused_count = None
            difficulty = None

        covered_ids = [oid for oid in targeted_ids if oid in covered_set]
        uncovered_ids = [oid for oid in targeted_ids if oid not in covered_set]

        return StudentExamResponse(
            attempt_id=attempt.id,
            assessment_id=attempt.assessment_id,
            course_id=course_id,
            assessment_type=assessment_type,
            status=attempt.status,
            requested_count=req_count,
            actual_count=len(exam_questions),
            unseen_question_count=unseen_count,
            reused_question_count=reused_count,
            targeted_outcome_ids=targeted_ids,
            covered_outcome_ids=covered_ids,
            uncovered_outcome_ids=uncovered_ids,
            difficulty=difficulty,
            resumed=resumed,
            started_at=attempt.started_at,
            questions=exam_questions,
        )

    def start_initial_exam(
        self,
        *,
        user: User,
        course_id: int,
        payload: InitialExamCreateRequest | None = None,
    ) -> StudentExamResponse:
        """Start or resume a student's diagnostic (initial) exam atomically.

        1. Authorizes active `Role.STUDENT` enrolled in `course_id`.
        2. Acquires Tier 2 `(student_id, course_id)` advisory lock.
        3. Resumes an existing `in_progress` diagnostic attempt if present, or
           rejects with `DiagnosticExamAlreadyCompletedError` if already completed.
        4. Selects active questions via balanced round-robin across outcomes.
        5. Creates `Assessment(diagnostic)`, ordered `AssessmentQuestion` rows
           (acquiring Tier 4 question locks), and `StudentAssessment(in_progress)`.
        6. Builds answer-stripped `StudentExamResponse` inside the transaction.
        """
        self._authorize_student_for_course(user=user, course_id=course_id)
        requested_count = (
            payload.question_count
            if payload is not None and payload.question_count is not None
            else self._settings.exam_initial_question_count
        )

        with self._tx.begin():
            # Tier 2 lock: serialize concurrent initial exam starts for (student, course).
            self._mastery.acquire_student_course_lock(
                student_id=user.id, course_id=course_id
            )

            outcomes = self._outcomes.list_by_course(course_id)
            outcome_ids_ordered = [lo.id for lo in outcomes]

            existing_attempts = self._assessments.list_attempts_for_student(
                student_id=user.id,
                course_id=course_id,
                assessment_type=AssessmentType.DIAGNOSTIC.value,
            )
            for existing in existing_attempts:
                if existing.status == StudentAssessmentStatus.IN_PROGRESS.value:
                    existing_assessment = self._assessments.get_assessment_for_course(
                        existing.assessment_id, course_id
                    )
                    existing_desc = (
                        getattr(existing_assessment, "description", None)
                        if existing_assessment is not None
                        else None
                    )
                    return self._build_attempt_response(
                        attempt=existing,
                        course_id=course_id,
                        assessment_type=AssessmentType.DIAGNOSTIC.value,
                        requested_count=requested_count,
                        outcome_ids_ordered=outcome_ids_ordered,
                        assessment_description=existing_desc,
                        resumed=True,
                    )
            if any(
                existing.status == StudentAssessmentStatus.COMPLETED.value
                for existing in existing_attempts
            ):
                raise DiagnosticExamAlreadyCompletedError(
                    "Initial diagnostic exam has already been completed for this course."
                )

            if not outcome_ids_ordered:
                raise InsufficientQuestionsError(
                    "No learning outcomes or active questions exist for this course."
                )

            assessment = None
            diag_meta_json = _encode_diagnostic_metadata(
                requested_count=requested_count,
                targeted_outcome_ids=outcome_ids_ordered,
            )
            for attempt_idx in range(_MAX_SELECTION_RETRIES):
                active_pool = self._questions.list_active_pool(course_id)
                rng = self._rng_factory() if self._rng_factory is not None else None
                selection = select_initial_exam_questions(
                    outcome_ids_ordered=outcome_ids_ordered,
                    active_questions=active_pool,
                    requested_count=requested_count,
                    rng=rng,
                )
                if selection.actual_count == 0:
                    raise InsufficientQuestionsError(
                        "No active questions are available for this course."
                    )

                try:
                    assessment, _ = self._assessments.create_assessment_with_questions(
                        course_id=course_id,
                        title="Initial Diagnostic Exam",
                        description=diag_meta_json,
                        assessment_type=AssessmentType.DIAGNOSTIC.value,
                        question_ids=[q.id for q in selection.questions],
                        created_by=user.id,
                    )
                    break
                except QuestionArchivedError:
                    if attempt_idx == _MAX_SELECTION_RETRIES - 1:
                        raise

            assert assessment is not None
            attempt = self._assessments.create_attempt(
                student_id=user.id,
                assessment_id=assessment.id,
                course_id=course_id,
            )
            response = self._build_attempt_response(
                attempt=attempt,
                course_id=course_id,
                assessment_type=AssessmentType.DIAGNOSTIC.value,
                requested_count=requested_count,
                outcome_ids_ordered=outcome_ids_ordered,
                assessment_description=diag_meta_json,
            )
        return response

    def get_student_exam(
        self,
        *,
        user: User,
        course_id: int,
        attempt_id: int,
    ) -> StudentExamResponse:
        """Return a student's own exam attempt without exposing correct answers."""
        self._authorize_student_for_course(user=user, course_id=course_id)

        attempt = self._assessments.get_attempt_for_student(
            attempt_id=attempt_id,
            student_id=user.id,
            course_id=course_id,
        )
        if attempt is None:
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)

        assessment = self._assessments.get_assessment_for_course(
            attempt.assessment_id, course_id
        )
        if assessment is None:
            raise ResourceNotFoundError(RESOURCE_NOT_FOUND_MESSAGE)

        outcomes = self._outcomes.list_by_course(course_id)
        outcome_ids_ordered = [lo.id for lo in outcomes]
        default_requested = (
            self._settings.exam_initial_question_count
            if assessment.assessment_type == AssessmentType.DIAGNOSTIC.value
            else self._settings.exam_retest_question_count
        )
        return self._build_attempt_response(
            attempt=attempt,
            course_id=course_id,
            assessment_type=assessment.assessment_type,
            requested_count=default_requested,
            outcome_ids_ordered=outcome_ids_ordered,
            assessment_description=getattr(assessment, "description", None),
        )

    def start_retest_exam(
        self,
        *,
        user: User,
        course_id: int,
        payload: RetestExamCreateRequest | None = None,
    ) -> StudentExamResponse:
        """Start or resume a student's review (retest) exam targeting weak outcomes.

        Supports both:
        - General retest (`learning_outcome_id is None`): selects across all weak,
          unblocked (`status == 'review'`) outcomes in priority order.
        - Targeted retest (`learning_outcome_id is not None`): verifies outcome
          belongs to `course_id` and is weak + unblocked (`status == 'review'`).

        Prioritizes unseen question lineages (`COALESCE(root_question_id, id)`)
        before reusing previously seen lineages. Never creates multiple concurrent
        in-progress review attempts for the same `(student, course)`.
        """
        self._authorize_student_for_course(user=user, course_id=course_id)
        requested_count = (
            payload.question_count
            if payload is not None and payload.question_count is not None
            else self._settings.exam_retest_question_count
        )
        requested_outcome_id = (
            payload.learning_outcome_id if payload is not None else None
        )
        requested_difficulty = payload.difficulty if payload is not None else None
        requested_difficulty_str = (
            requested_difficulty.value if requested_difficulty is not None else None
        )

        with self._tx.begin():
            # Tier 2 lock: serialize concurrent retest starts for (student, course).
            self._mastery.acquire_student_course_lock(
                student_id=user.id, course_id=course_id
            )

            # 1. Diagnostic exam must be completed first.
            completed_diagnostics = self._assessments.list_attempts_for_student(
                student_id=user.id,
                course_id=course_id,
                assessment_type=AssessmentType.DIAGNOSTIC.value,
                status=StudentAssessmentStatus.COMPLETED.value,
                limit=1,
            )
            if not completed_diagnostics:
                raise DiagnosticExamRequiredError(
                    "Initial diagnostic exam must be completed before starting a retest."
                )

            outcomes = self._outcomes.list_by_course(course_id)
            outcome_ids_ordered = [lo.id for lo in outcomes]
            course_outcome_set = set(outcome_ids_ordered)

            if (
                requested_outcome_id is not None
                and requested_outcome_id not in course_outcome_set
            ):
                raise CrossCourseReferenceError(
                    "Requested learning outcome does not belong to this course."
                )

            # 2. Check for an existing in-progress review attempt.
            in_progress_reviews = self._assessments.list_attempts_for_student(
                student_id=user.id,
                course_id=course_id,
                assessment_type=AssessmentType.REVIEW.value,
                status=StudentAssessmentStatus.IN_PROGRESS.value,
                limit=1,
            )
            if in_progress_reviews:
                existing_attempt = in_progress_reviews[0]
                existing_assessment = self._assessments.get_assessment_for_course(
                    existing_attempt.assessment_id, course_id
                )
                existing_desc = (
                    getattr(existing_assessment, "description", None)
                    if existing_assessment is not None
                    else None
                )
                existing_meta = _decode_retest_metadata(existing_desc)
                if (
                    existing_meta is not None
                    and existing_meta.requested_outcome_id == requested_outcome_id
                    and existing_meta.difficulty == requested_difficulty
                    and existing_meta.requested_count == requested_count
                ):
                    return self._build_attempt_response(
                        attempt=existing_attempt,
                        course_id=course_id,
                        assessment_type=AssessmentType.REVIEW.value,
                        requested_count=requested_count,
                        outcome_ids_ordered=outcome_ids_ordered,
                        assessment_description=existing_desc,
                        resumed=True,
                    )
                raise ActiveRetestConflictError(
                    "An in-progress review exam already exists with different parameters."
                )

            # 3. Determine eligible outcomes using live graph-consistent recommendations
            # (same read-only projection as GET /recommendations, so graph changes take
            # effect immediately without stale persisted statuses).
            threshold = self._settings.exam_default_mastery_threshold
            prerequisites = self._outcomes.list_prerequisites_by_course(course_id)
            live_recs = compute_live_recommendations(
                student_id=user.id,
                course_id=course_id,
                outcomes=outcomes,
                prerequisites=prerequisites,
                mastery_repository=self._mastery,
                mastery_threshold=threshold,
            )
            eligible_outcome_ids = [
                rec.learning_outcome_id
                for rec in live_recs
                if rec.status == "review"
            ]

            if requested_outcome_id is not None:
                if requested_outcome_id not in set(eligible_outcome_ids):
                    raise OutcomeNotEligibleForRetestError(
                        "Requested learning outcome is not eligible for retest "
                        "(it may already be mastered, blocked by prerequisites, or unassessed)."
                    )
                targeted_outcome_ids = [requested_outcome_id]
            else:
                if not eligible_outcome_ids:
                    raise NoEligibleOutcomesForRetestError(
                        "No weak, unblocked learning outcomes are eligible for retest."
                    )
                targeted_outcome_ids = eligible_outcome_ids

            # 4. Select unseen-prioritized questions with retry on concurrent archive.
            seen_lineages = self._assessments.get_seen_question_lineage_ids(
                student_id=user.id, course_id=course_id
            )
            assessment: Assessment | None = None
            meta_json = ""
            for attempt_idx in range(_MAX_SELECTION_RETRIES):
                active_pool = self._questions.list_active_pool(
                    course_id,
                    learning_outcome_ids=targeted_outcome_ids,
                    difficulty_level=requested_difficulty_str,
                )
                rng = self._rng_factory() if self._rng_factory is not None else None
                selection = select_retest_questions(
                    targeted_outcome_ids=targeted_outcome_ids,
                    active_questions=active_pool,
                    seen_lineage_ids=seen_lineages,
                    requested_count=requested_count,
                    difficulty=requested_difficulty,
                    rng=rng,
                )
                if selection.actual_count == 0:
                    raise InsufficientQuestionsError(
                        "No active questions match the retest target outcomes and difficulty."
                    )

                meta_json = _encode_retest_metadata(
                    requested_count=selection.requested_count,
                    unseen_question_count=selection.unseen_question_count,
                    reused_question_count=selection.reused_question_count,
                    targeted_outcome_ids=selection.targeted_outcome_ids,
                    requested_outcome_id=requested_outcome_id,
                    difficulty=requested_difficulty,
                )
                try:
                    assessment, _ = self._assessments.create_assessment_with_questions(
                        course_id=course_id,
                        title="Targeted Review Exam",
                        description=meta_json,
                        assessment_type=AssessmentType.REVIEW.value,
                        question_ids=[q.id for q in selection.questions],
                        created_by=user.id,
                    )
                    break
                except QuestionArchivedError:
                    if attempt_idx == _MAX_SELECTION_RETRIES - 1:
                        raise

            assert assessment is not None
            attempt = self._assessments.create_attempt(
                student_id=user.id,
                assessment_id=assessment.id,
                course_id=course_id,
            )
            response = self._build_attempt_response(
                attempt=attempt,
                course_id=course_id,
                assessment_type=AssessmentType.REVIEW.value,
                requested_count=requested_count,
                outcome_ids_ordered=outcome_ids_ordered,
                assessment_description=meta_json,
            )
        return response
