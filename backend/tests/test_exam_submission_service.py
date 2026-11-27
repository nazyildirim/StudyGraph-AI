"""Stateless unit tests for ExamSubmissionService, schemas, and pure grading."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

from pydantic import ValidationError
import pytest

from app.authorization.course_access_policy import CourseAccessPolicy
from app.authorization.ownership import ResourceNotFoundError, RoleAuthorizationError
from app.models.assessment import AssessmentType
from app.models.student_assessment import StudentAssessmentStatus
from app.repositories.assessment_repository import StudentResponseDraft
from app.repositories.errors import (
    AttemptAlreadyFinalizedError,
    DuplicateResponseError,
    InvalidResponseError,
)
from app.schemas.exam import (
    ExamSubmitRequest,
    StudentAnswerRequest,
)
from app.services.exam_submission_service import (
    AttemptNotCompletedError,
    ExamSubmissionService,
    grade_exam_submission,
)


def _q(qid: int, outcome_id: int = 100, points: float = 1.0) -> SimpleNamespace:
    return SimpleNamespace(
        id=qid,
        learning_outcome_id=outcome_id,
        points=points,
    )


def _opts(qid: int, correct_idx: int = 0) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            id=qid * 100 + i,
            question_id=qid,
            option_text=f"Opt {i}",
            is_correct=(i == correct_idx),
            order_index=i,
        )
        for i in range(4)
    ]


# --- Pure Grading Engine Tests ---


def test_grade_all_correct_all_wrong_mixed_and_weighted_points() -> None:
    assigned = [
        (0, _q(1, 100, points=1.0)),
        (1, _q(2, 101, points=3.0)),
        (2, _q(3, 102, points=6.0)),
    ]
    opts_map = {1: _opts(1, 0), 2: _opts(2, 1), 3: _opts(3, 2)}

    # All correct -> 100.0
    all_ok = grade_exam_submission(
        assigned_questions=assigned,  # type: ignore[arg-type]
        options_by_question_id=opts_map,  # type: ignore[arg-type]
        submitted_answers=[
            StudentAnswerRequest(question_id=1, selected_option_id=100),
            StudentAnswerRequest(question_id=2, selected_option_id=201),
            StudentAnswerRequest(question_id=3, selected_option_id=302),
        ],
    )
    assert all_ok.score == 100.0
    assert all_ok.correct_count == 3
    assert all_ok.incorrect_count == 0
    assert all_ok.unanswered_count == 0
    assert all_ok.earned_points == 10.0
    assert all_ok.total_possible_points == 10.0

    # All wrong -> 0.0
    all_bad = grade_exam_submission(
        assigned_questions=assigned,  # type: ignore[arg-type]
        options_by_question_id=opts_map,  # type: ignore[arg-type]
        submitted_answers=[
            StudentAnswerRequest(question_id=1, selected_option_id=101),
            StudentAnswerRequest(question_id=2, selected_option_id=200),
            StudentAnswerRequest(question_id=3, selected_option_id=300),
        ],
    )
    assert all_bad.score == 0.0
    assert all_bad.correct_count == 0
    assert all_bad.incorrect_count == 3
    assert all_bad.unanswered_count == 0
    assert all_bad.earned_points == 0.0

    # Mixed: Q1 correct (1pt), Q2 wrong (0pt), Q3 omitted -> unanswered (0pt) => 1/10 = 10.0%
    mixed = grade_exam_submission(
        assigned_questions=assigned,  # type: ignore[arg-type]
        options_by_question_id=opts_map,  # type: ignore[arg-type]
        submitted_answers=[
            StudentAnswerRequest(question_id=1, selected_option_id=100),
            StudentAnswerRequest(question_id=2, selected_option_id=200),
        ],
    )
    assert mixed.total_questions == 3
    assert mixed.correct_count == 1
    assert mixed.incorrect_count == 1
    assert mixed.unanswered_count == 1
    assert mixed.correct_count + mixed.incorrect_count + mixed.unanswered_count == 3
    assert mixed.earned_points == 1.0
    assert mixed.score == 10.0
    assert mixed.response_drafts[2].selected_option_id is None
    assert mixed.response_drafts[2].is_correct is False
    assert mixed.response_drafts[2].score_earned == 0.0


def test_grade_rejects_unassigned_question_mismatched_option_and_duplicates() -> None:
    assigned = [(0, _q(1, 100, 1.0)), (1, _q(2, 100, 1.0))]
    opts_map = {1: _opts(1, 0), 2: _opts(2, 0)}

    # Unassigned question
    with pytest.raises(InvalidResponseError):
        grade_exam_submission(
            assigned_questions=assigned,  # type: ignore[arg-type]
            options_by_question_id=opts_map,  # type: ignore[arg-type]
            submitted_answers=[
                StudentAnswerRequest(question_id=999, selected_option_id=100)
            ],
        )

    # Option belonging to Q2 submitted for Q1
    with pytest.raises(InvalidResponseError):
        grade_exam_submission(
            assigned_questions=assigned,  # type: ignore[arg-type]
            options_by_question_id=opts_map,  # type: ignore[arg-type]
            submitted_answers=[
                StudentAnswerRequest(question_id=1, selected_option_id=200)
            ],
        )

    # Duplicate question_id passed directly to grading engine
    with pytest.raises(DuplicateResponseError):
        grade_exam_submission(
            assigned_questions=assigned,  # type: ignore[arg-type]
            options_by_question_id=opts_map,  # type: ignore[arg-type]
            submitted_answers=[
                StudentAnswerRequest(question_id=1, selected_option_id=100),
                StudentAnswerRequest(question_id=1, selected_option_id=101),
            ],
        )


# --- Schema Manipulation & Validation Tests ---


def test_submit_schema_forbids_client_grading_fields_duplicates_and_bool_ids() -> None:
    for forbidden in (
        {"is_correct": True},
        {"score": 100.0},
        {"score_earned": 5.0},
        {"student_id": 1},
        {"learning_outcome_id": 10},
        {"status": "completed"},
        {"completed_at": "2026-11-28T00:00:00Z"},
    ):
        with pytest.raises(ValidationError):
            StudentAnswerRequest(
                question_id=1, selected_option_id=100, **forbidden  # type: ignore[arg-type]
            )

    with pytest.raises(ValidationError):
        StudentAnswerRequest(question_id=True, selected_option_id=100)  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        ExamSubmitRequest(
            answers=[
                StudentAnswerRequest(question_id=1, selected_option_id=100),
                StudentAnswerRequest(question_id=1, selected_option_id=101),
            ]
        )

    with pytest.raises(ValidationError):
        ExamSubmitRequest(
            answers=[
                StudentAnswerRequest(question_id=i + 1, selected_option_id=None)
                for i in range(201)
            ]
        )


# --- Service Authorization, State, and Rollback Tests ---


class _FakeTx:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    @contextmanager
    def begin(self) -> Iterator[None]:
        try:
            yield
            self.commits += 1
        except Exception:
            self.rollbacks += 1
            raise


class _FakeCourseRepo:
    def __init__(self, courses: dict[int, SimpleNamespace]) -> None:
        self._courses = courses

    def get_by_id(self, course_id: int) -> SimpleNamespace | None:
        return self._courses.get(course_id)


class _FakeEnrollmentRepo:
    def __init__(self, enrolled: set[tuple[int, int]]) -> None:
        self._enrolled = enrolled

    def has_active_enrollment(self, student_id: int, course_id: int) -> bool:
        return (student_id, course_id) in self._enrolled


class _FakeMasteryRepo:
    def __init__(self) -> None:
        self.locks: list[tuple[int, int]] = []

    def acquire_student_course_lock(self, *, student_id: int, course_id: int) -> None:
        self.locks.append((student_id, course_id))


class _FakeQuestionRepo:
    def __init__(self) -> None:
        self._qs = {1: _q(1, 100, 2.0), 2: _q(2, 101, 2.0)}
        self._opts = {1: _opts(1, 0), 2: _opts(2, 1)}

    def list_by_ids(self, question_ids: Sequence[int]) -> list[SimpleNamespace]:
        return [self._qs[qid] for qid in question_ids if qid in self._qs]

    def list_options_for_questions(
        self, question_ids: Sequence[int]
    ) -> dict[int, list[SimpleNamespace]]:
        return {qid: self._opts[qid] for qid in question_ids if qid in self._opts}


class _FakeAssessmentRepo:
    def __init__(self, *, status: str = StudentAssessmentStatus.IN_PROGRESS.value, fail_save: bool = False) -> None:
        self.assessment = SimpleNamespace(
            id=10,
            course_id=10,
            title="Initial Diagnostic Exam",
            assessment_type=AssessmentType.DIAGNOSTIC.value,
        )
        self.attempt = SimpleNamespace(
            id=1,
            student_id=1,
            assessment_id=10,
            status=status,
            score=None,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc) if status == "completed" else None,
        )
        self.responses: list[SimpleNamespace] = []
        self._fail_save = fail_save

    def get_assessment_for_course(self, assessment_id: int, course_id: int) -> SimpleNamespace | None:
        if assessment_id == self.assessment.id and course_id == self.assessment.course_id:
            return self.assessment
        return None

    def list_assessments_by_ids(self, assessment_ids: Sequence[int]) -> dict[int, SimpleNamespace]:
        return {self.assessment.id: self.assessment} if self.assessment.id in assessment_ids else {}

    def list_assessment_questions(self, assessment_id: int, *, course_id: int | None = None) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(assessment_id=assessment_id, question_id=1, order_index=0),
            SimpleNamespace(assessment_id=assessment_id, question_id=2, order_index=1),
        ]

    def get_attempt_for_student(
        self, *, attempt_id: int, student_id: int, course_id: int | None = None, for_update: bool = False
    ) -> SimpleNamespace | None:
        if attempt_id != self.attempt.id or student_id != self.attempt.student_id:
            return None
        if course_id is not None and course_id != self.assessment.course_id:
            return None
        return self.attempt

    def list_attempts_for_student(
        self, *, student_id: int, course_id: int, limit: int = 50, offset: int = 0
    ) -> list[SimpleNamespace]:
        if student_id == self.attempt.student_id and course_id == self.assessment.course_id:
            return [self.attempt]
        return []

    def list_responses_for_attempt(self, *, attempt_id: int, student_id: int) -> list[SimpleNamespace]:
        return list(self.responses) if attempt_id == self.attempt.id and student_id == self.attempt.student_id else []

    def save_responses_and_complete_attempt(
        self,
        *,
        attempt_id: int,
        student_id: int,
        course_id: int,
        responses: Sequence[StudentResponseDraft],
        score: float,
        completed_at: datetime | None = None,
    ) -> tuple[SimpleNamespace, list[SimpleNamespace]]:
        if self._fail_save:
            raise RuntimeError("Simulated DB error on save")
        self.responses = [
            SimpleNamespace(
                question_id=r.question_id,
                selected_option_id=r.selected_option_id,
                is_correct=r.is_correct,
                score_earned=r.score_earned,
            )
            for r in responses
        ]
        self.attempt.status = StudentAssessmentStatus.COMPLETED.value
        self.attempt.score = score
        self.attempt.completed_at = completed_at or datetime.now(timezone.utc)
        return self.attempt, self.responses


def _make_submission_service(
    *, status: str = StudentAssessmentStatus.IN_PROGRESS.value, fail_save: bool = False
) -> tuple[ExamSubmissionService, _FakeTx]:
    policy = CourseAccessPolicy(
        course_repository=_FakeCourseRepo(
            {
                10: SimpleNamespace(id=10, instructor_id=2, is_active=True),
                20: SimpleNamespace(id=20, instructor_id=2, is_active=True),
            }
        ),
        enrollment_repository=_FakeEnrollmentRepo({(1, 10), (1, 20), (5, 10)}),
    )
    tx = _FakeTx()
    svc = ExamSubmissionService(
        access_policy=policy,
        assessment_repository=_FakeAssessmentRepo(status=status, fail_save=fail_save),  # type: ignore[arg-type]
        question_repository=_FakeQuestionRepo(),  # type: ignore[arg-type]
        mastery_repository=_FakeMasteryRepo(),  # type: ignore[arg-type]
        transaction_manager=tx,
        allow_skip_mastery_integration=True,
    )
    return svc, tx


def test_submission_authorization_abandoned_completed_in_progress_result_and_rollback() -> None:
    stu1 = SimpleNamespace(id=1, role="student", is_active=True)
    stu2 = SimpleNamespace(id=5, role="student", is_active=True)
    unenrolled = SimpleNamespace(id=9, role="student", is_active=True)
    inactive = SimpleNamespace(id=1, role="student", is_active=False)
    instructor = SimpleNamespace(id=2, role="instructor", is_active=True)
    admin = SimpleNamespace(id=99, role="admin", is_active=True)
    payload = ExamSubmitRequest(
        answers=[StudentAnswerRequest(question_id=1, selected_option_id=100)]
    )

    svc, tx = _make_submission_service()

    # Instructor/admin rejected -> RoleAuthorizationError
    for actor in (instructor, admin):
        with pytest.raises(RoleAuthorizationError):
            svc.submit_exam(user=actor, course_id=10, attempt_id=1, payload=payload)

    # Unenrolled, inactive, other student, other course -> ResourceNotFoundError
    for actor, cid in ((unenrolled, 10), (inactive, 10), (stu2, 10), (stu1, 20)):
        with pytest.raises(ResourceNotFoundError):
            svc.submit_exam(user=actor, course_id=cid, attempt_id=1, payload=payload)

    # In-progress attempt cannot leak results via get_exam_result
    with pytest.raises(AttemptNotCompletedError):
        svc.get_exam_result(user=stu1, course_id=10, attempt_id=1)

    # Abandoned attempt cannot be submitted
    abandoned_svc, _ = _make_submission_service(
        status=StudentAssessmentStatus.ABANDONED.value
    )
    with pytest.raises(AttemptAlreadyFinalizedError):
        abandoned_svc.submit_exam(user=stu1, course_id=10, attempt_id=1, payload=payload)

    # Valid submit succeeds; second submit rejected
    res = svc.submit_exam(user=stu1, course_id=10, attempt_id=1, payload=payload)
    assert res.score == 50.0
    assert res.correct_count == 1
    assert res.unanswered_count == 1
    assert tx.commits == 1

    with pytest.raises(AttemptAlreadyFinalizedError):
        svc.submit_exam(user=stu1, course_id=10, attempt_id=1, payload=payload)

    # Mid-transaction DB failure rolls back cleanly
    fail_svc, fail_tx = _make_submission_service(fail_save=True)
    with pytest.raises(RuntimeError):
        fail_svc.submit_exam(user=stu1, course_id=10, attempt_id=1, payload=payload)
    assert fail_tx.commits == 0
    assert fail_tx.rollbacks == 1
