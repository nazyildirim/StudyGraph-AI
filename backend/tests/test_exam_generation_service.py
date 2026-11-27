"""Stateless unit tests for initial exam selection, schemas, and ExamGenerationService."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
import random
from types import SimpleNamespace

from pydantic import ValidationError
import pytest

from app.authorization.course_access_policy import CourseAccessPolicy
from app.authorization.ownership import ResourceNotFoundError, RoleAuthorizationError
from app.core.config import Settings
from app.models.assessment import AssessmentType
from app.models.question import DifficultyLevel, QuestionType
from app.models.student_assessment import StudentAssessmentStatus
from app.schemas.exam import (
    InitialExamCreateRequest,
    StudentExamOptionResponse,
    StudentExamQuestionResponse,
    StudentExamResponse,
)
from app.services.exam_generation_service import (
    DiagnosticExamAlreadyCompletedError,
    ExamGenerationService,
    InsufficientQuestionsError,
    select_initial_exam_questions,
)


def _q(
    qid: int,
    outcome_id: int,
    *,
    course_id: int = 10,
    is_active: bool = True,
    version_number: int = 1,
    root_question_id: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=qid,
        course_id=course_id,
        learning_outcome_id=outcome_id,
        question_text=f"Question {qid}",
        question_type=QuestionType.MULTIPLE_CHOICE.value,
        difficulty_level=DifficultyLevel.MEDIUM.value,
        points=1.0,
        is_active=is_active,
        version_number=version_number,
        root_question_id=root_question_id,
    )


def _opts(qid: int) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            id=qid * 10 + idx,
            question_id=qid,
            option_text=f"Opt {idx}",
            is_correct=(idx == 0),
            order_index=idx,
        )
        for idx in range(4)
    ]


# --- Pure Algorithm Unit Tests ---


def test_balanced_round_robin_15_questions_across_5_outcomes() -> None:
    outcomes = [1, 2, 3, 4, 5]
    pool = [_q(oid * 10 + i, oid) for oid in outcomes for i in range(4)]

    sel = select_initial_exam_questions(
        outcome_ids_ordered=outcomes,
        active_questions=pool,
        requested_count=15,
        rng=random.Random(42),
    )
    assert sel.requested_count == 15
    assert sel.actual_count == 15
    assert sel.uncovered_outcome_ids == ()
    counts = Counter(q.learning_outcome_id for q in sel.questions)
    assert counts == {1: 3, 2: 3, 3: 3, 4: 3, 5: 3}
    assert len({q.id for q in sel.questions}) == 15


def test_unbalanced_pools_fill_remaining_quota_and_report_empty_outcomes() -> None:
    outcomes = [1, 2, 3, 4]
    pool = [
        _q(101, 1),  # only 1 question in LO 1
        # LO 2 has 0 questions
        *[_q(300 + i, 3) for i in range(10)],
        *[_q(400 + i, 4) for i in range(10)],
    ]
    sel = select_initial_exam_questions(
        outcome_ids_ordered=outcomes,
        active_questions=pool,
        requested_count=15,
        rng=random.Random(7),
    )
    assert sel.actual_count == 15
    assert sel.uncovered_outcome_ids == (2,)
    counts = Counter(q.learning_outcome_id for q in sel.questions)
    assert counts == {1: 1, 3: 7, 4: 7}


def test_insufficient_pool_and_more_outcomes_than_requested_count() -> None:
    # Fewer than 15 available -> returns all 6 without repeating
    sel_small = select_initial_exam_questions(
        outcome_ids_ordered=[1, 2, 3],
        active_questions=[_q(1, 1), _q(2, 1), _q(3, 2), _q(4, 2), _q(5, 3), _q(6, 3)],
        requested_count=15,
        rng=random.Random(1),
    )
    assert sel_small.requested_count == 15
    assert sel_small.actual_count == 6
    assert len({q.id for q in sel_small.questions}) == 6

    # More outcomes (8) than requested_count (5) -> prioritizes first 5 in curriculum order
    sel_many_lo = select_initial_exam_questions(
        outcome_ids_ordered=[10, 20, 30, 40, 50, 60, 70, 80],
        active_questions=[_q(oid + 1, oid) for oid in [10, 20, 30, 40, 50, 60, 70, 80]],
        requested_count=5,
        rng=random.Random(1),
    )
    assert sel_many_lo.actual_count == 5
    assert [q.learning_outcome_id for q in sel_many_lo.questions] == [10, 20, 30, 40, 50]
    assert sel_many_lo.uncovered_outcome_ids == (60, 70, 80)


def test_excludes_archived_cross_course_and_duplicate_lineage_questions() -> None:
    pool = [
        _q(1, 100, is_active=False),  # archived -> excluded
        _q(2, 999, course_id=20),  # other course outcome -> excluded
        _q(3, 100, version_number=1, root_question_id=None),
        _q(4, 100, version_number=2, root_question_id=3),  # same lineage as 3 -> deduplicated
    ]
    sel = select_initial_exam_questions(
        outcome_ids_ordered=[100],
        active_questions=pool,
        requested_count=5,
        rng=random.Random(3),
    )
    assert sel.actual_count == 1
    assert sel.questions[0].id == 4  # latest version in lineage kept


# --- Schema Security Tests ---


def test_exam_request_forbids_server_fields_and_response_hides_answers() -> None:
    for bad_field in (
        {"student_id": 1},
        {"score": 100.0},
        {"status": "completed"},
        {"assessment_type": "review"},
        {"question_count": True},
    ):
        with pytest.raises(ValidationError):
            InitialExamCreateRequest(**bad_field)  # type: ignore[arg-type]

    forbidden = {"is_correct", "answer", "correct_option_id", "correct_answer"}
    assert not (forbidden & set(StudentExamResponse.model_fields))
    assert not (forbidden & set(StudentExamQuestionResponse.model_fields))
    assert not (forbidden & set(StudentExamOptionResponse.model_fields))

    q_resp = StudentExamQuestionResponse.from_models(
        question=_q(1, 100),  # type: ignore[arg-type]
        order_index=0,
        options=_opts(1),  # type: ignore[arg-type]
    ).model_dump()
    assert not (forbidden & set(q_resp.keys()))
    for opt in q_resp["options"]:
        assert not (forbidden & set(opt.keys()))


# --- Service Authorization & Lifecycle Unit Tests ---


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


class _FakeOutcomeRepo:
    def __init__(self, by_course: dict[int, list[SimpleNamespace]]) -> None:
        self._by_course = by_course

    def list_by_course(self, course_id: int) -> list[SimpleNamespace]:
        return list(self._by_course.get(course_id, []))


class _FakeQuestionRepo:
    def __init__(self, questions: list[SimpleNamespace]) -> None:
        self._questions = {q.id: q for q in questions}

    def list_active_pool(self, course_id: int, **_: object) -> list[SimpleNamespace]:
        return [
            q
            for q in self._questions.values()
            if q.course_id == course_id and q.is_active
        ]

    def list_by_ids(self, question_ids: Sequence[int]) -> list[SimpleNamespace]:
        return [self._questions[qid] for qid in question_ids if qid in self._questions]

    def list_options_for_questions(
        self, question_ids: Sequence[int]
    ) -> dict[int, list[SimpleNamespace]]:
        return {qid: _opts(qid) for qid in question_ids}


class _FakeMasteryRepo:
    def __init__(self) -> None:
        self.locks: list[tuple[int, int]] = []

    def acquire_student_course_lock(self, *, student_id: int, course_id: int) -> None:
        self.locks.append((student_id, course_id))


class _FakeAssessmentRepo:
    def __init__(self, *, fail_on_attempt: bool = False) -> None:
        self._assessments: dict[int, SimpleNamespace] = {}
        self._aq: dict[int, list[SimpleNamespace]] = {}
        self._attempts: dict[int, SimpleNamespace] = {}
        self._fail_on_attempt = fail_on_attempt

    def create_assessment_with_questions(
        self,
        *,
        course_id: int,
        title: str,
        assessment_type: str,
        question_ids: Sequence[int],
        created_by: int | None = None,
        **_: object,
    ) -> tuple[SimpleNamespace, list[SimpleNamespace]]:
        aid = len(self._assessments) + 1
        assessment = SimpleNamespace(
            id=aid,
            course_id=course_id,
            title=title,
            assessment_type=assessment_type,
            created_by=created_by,
        )
        aqs = [
            SimpleNamespace(assessment_id=aid, question_id=qid, order_index=i)
            for i, qid in enumerate(question_ids)
        ]
        self._assessments[aid] = assessment
        self._aq[aid] = aqs
        return assessment, aqs

    def get_assessment_for_course(
        self, assessment_id: int, course_id: int
    ) -> SimpleNamespace | None:
        a = self._assessments.get(assessment_id)
        return a if (a is not None and a.course_id == course_id) else None

    def list_assessment_questions(
        self, assessment_id: int, *, course_id: int | None = None
    ) -> list[SimpleNamespace]:
        return list(self._aq.get(assessment_id, []))

    def create_attempt(
        self, *, student_id: int, assessment_id: int, course_id: int
    ) -> SimpleNamespace:
        if self._fail_on_attempt:
            raise RuntimeError("Simulated attempt insert error")
        tid = len(self._attempts) + 1
        attempt = SimpleNamespace(
            id=tid,
            student_id=student_id,
            assessment_id=assessment_id,
            status=StudentAssessmentStatus.IN_PROGRESS.value,
            started_at=datetime.now(timezone.utc),
        )
        self._attempts[tid] = attempt
        return attempt

    def get_attempt_for_student(
        self,
        *,
        attempt_id: int,
        student_id: int,
        course_id: int | None = None,
        for_update: bool = False,
    ) -> SimpleNamespace | None:
        att = self._attempts.get(attempt_id)
        if att is None or att.student_id != student_id:
            return None
        if course_id is not None:
            a = self._assessments.get(att.assessment_id)
            if a is None or a.course_id != course_id:
                return None
        return att

    def list_attempts_for_student(
        self,
        *,
        student_id: int,
        course_id: int,
        assessment_type: str | None = None,
        status: str | None = None,
        **_: object,
    ) -> list[SimpleNamespace]:
        out = []
        for att in self._attempts.values():
            if att.student_id != student_id:
                continue
            a = self._assessments[att.assessment_id]
            if a.course_id != course_id:
                continue
            if assessment_type is not None and a.assessment_type != assessment_type:
                continue
            if status is not None and att.status != status:
                continue
            out.append(att)
        return out


def _make_service(
    questions: list[SimpleNamespace],
    *,
    fail_on_attempt: bool = False,
) -> tuple[ExamGenerationService, _FakeAssessmentRepo, _FakeTx]:
    policy = CourseAccessPolicy(
        course_repository=_FakeCourseRepo(
            {10: SimpleNamespace(id=10, instructor_id=2, is_active=True)}
        ),
        enrollment_repository=_FakeEnrollmentRepo({(1, 10), (5, 10)}),
    )
    a_repo = _FakeAssessmentRepo(fail_on_attempt=fail_on_attempt)
    tx = _FakeTx()
    service = ExamGenerationService(
        access_policy=policy,
        assessment_repository=a_repo,  # type: ignore[arg-type]
        question_repository=_FakeQuestionRepo(questions),  # type: ignore[arg-type]
        learning_outcome_repository=_FakeOutcomeRepo(
            {10: [SimpleNamespace(id=100), SimpleNamespace(id=101)]}
        ),  # type: ignore[arg-type]
        mastery_repository=_FakeMasteryRepo(),  # type: ignore[arg-type]
        transaction_manager=tx,
        settings=Settings(_env_file=None),
        rng_factory=lambda: random.Random(123),
    )
    return service, a_repo, tx


def test_authorization_empty_pool_resume_completed_and_rollback() -> None:
    enrolled_stu = SimpleNamespace(id=1, role="student", is_active=True)
    other_stu = SimpleNamespace(id=5, role="student", is_active=True)
    unenrolled_stu = SimpleNamespace(id=9, role="student", is_active=True)
    inactive_stu = SimpleNamespace(id=1, role="student", is_active=False)
    instructor = SimpleNamespace(id=2, role="instructor", is_active=True)
    admin = SimpleNamespace(id=99, role="admin", is_active=True)

    # Empty pool -> InsufficientQuestionsError
    empty_svc, _, empty_tx = _make_service([])
    with pytest.raises(InsufficientQuestionsError):
        empty_svc.start_initial_exam(user=enrolled_stu, course_id=10)
    assert empty_tx.commits == 0

    svc, a_repo, tx = _make_service([_q(1, 100), _q(2, 101)])

    # Instructor / admin -> RoleAuthorizationError; unenrolled / inactive -> ResourceNotFoundError
    for actor in (instructor, admin):
        with pytest.raises(RoleAuthorizationError):
            svc.start_initial_exam(user=actor, course_id=10)
    for actor in (unenrolled_stu, inactive_stu):
        with pytest.raises(ResourceNotFoundError):
            svc.start_initial_exam(user=actor, course_id=10)
    assert tx.commits == 0

    # Enrolled student starts exam -> resumed with same attempt_id
    first = svc.start_initial_exam(user=enrolled_stu, course_id=10)
    resumed = svc.start_initial_exam(user=enrolled_stu, course_id=10)
    assert first.attempt_id == resumed.attempt_id
    assert first.actual_count == 2
    assert first.requested_count == 15

    # Other student cannot view attempt
    with pytest.raises(ResourceNotFoundError):
        svc.get_student_exam(user=other_stu, course_id=10, attempt_id=first.attempt_id)

    # Completed diagnostic blocks creating a new diagnostic
    a_repo._attempts[first.attempt_id].status = StudentAssessmentStatus.COMPLETED.value
    with pytest.raises(DiagnosticExamAlreadyCompletedError):
        svc.start_initial_exam(user=enrolled_stu, course_id=10)

    # Mid-transaction error triggers rollback
    fail_svc, _, fail_tx = _make_service([_q(1, 100)], fail_on_attempt=True)
    with pytest.raises(RuntimeError):
        fail_svc.start_initial_exam(user=enrolled_stu, course_id=10)
    assert fail_tx.commits == 0
    assert fail_tx.rollbacks == 1
