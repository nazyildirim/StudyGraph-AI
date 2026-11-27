"""Stateless unit tests for QuestionBankService and Question Pydantic schemas."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

from pydantic import ValidationError
import pytest

from app.authorization.course_access_policy import CourseAccessPolicy
from app.authorization.ownership import ResourceNotFoundError, RoleAuthorizationError
from app.models.question import DifficultyLevel, Question, QuestionType
from app.models.question_option import QuestionOption
from app.repositories.errors import CrossCourseReferenceError, QuestionNotFoundError
from app.repositories.question_repository import QuestionOptionDraft
from app.schemas.question import (
    QuestionCreateRequest,
    QuestionOptionCreate,
    QuestionStudentOptionResponse,
    QuestionStudentResponse,
    QuestionUpdateRequest,
)
from app.services.question_bank_service import QuestionBankService


def _valid_options(correct_idx: int = 0) -> list[dict[str, object]]:
    return [
        {
            "option_text": f"Choice {i}",
            "is_correct": i == correct_idx,
            "order_index": i,
        }
        for i in range(4)
    ]


def _make_user(user_id: int, role: str, is_active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, role=role, is_active=is_active)


def _make_course(course_id: int, instructor_id: int, is_active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=course_id, instructor_id=instructor_id, is_active=is_active)


class _FakeCourseRepo:
    def __init__(self, courses: dict[int, SimpleNamespace]) -> None:
        self._courses = courses

    def get_by_id(self, course_id: int) -> SimpleNamespace | None:
        return self._courses.get(course_id)


class _FakeEnrollmentRepo:
    def __init__(self, enrolled: set[tuple[int, int]] | None = None) -> None:
        self._enrolled = enrolled or set()

    def has_active_enrollment(self, student_id: int, course_id: int) -> bool:
        return (student_id, course_id) in self._enrolled


class _FakeOutcomeRepo:
    def __init__(self, outcomes: dict[int, int]) -> None:
        # outcome_id -> course_id
        self._outcomes = outcomes

    def get_by_id_for_course(
        self, outcome_id: int, course_id: int
    ) -> SimpleNamespace | None:
        if self._outcomes.get(outcome_id) == course_id:
            return SimpleNamespace(id=outcome_id, course_id=course_id)
        return None


class _FakeTxManager:
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


class _FakeQuestionRepo:
    def __init__(self, *, fail_on_create: bool = False) -> None:
        self._next_q_id = 1
        self._next_opt_id = 1
        self._questions: dict[int, SimpleNamespace] = {}
        self._options: dict[int, list[SimpleNamespace]] = {}
        self._used: set[int] = set()
        self._fail_on_create = fail_on_create
        self.mutation_calls = 0

    def mark_used(self, question_id: int) -> None:
        self._used.add(question_id)

    def get_by_id_for_course(
        self, question_id: int, course_id: int
    ) -> SimpleNamespace | None:
        q = self._questions.get(question_id)
        if q is None or q.course_id != course_id:
            return None
        return q

    def list_options(self, question_id: int) -> list[SimpleNamespace]:
        return list(self._options.get(question_id, []))

    def list_options_for_questions(
        self, question_ids: Sequence[int]
    ) -> dict[int, list[SimpleNamespace]]:
        return {qid: list(self._options.get(qid, [])) for qid in question_ids}

    def list_by_course(
        self,
        course_id: int,
        *,
        learning_outcome_id: int | None = None,
        difficulty_level: str | None = None,
        active_only: bool = True,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[SimpleNamespace]:
        items = [q for q in self._questions.values() if q.course_id == course_id]
        if learning_outcome_id is not None:
            items = [q for q in items if q.learning_outcome_id == learning_outcome_id]
        if difficulty_level is not None:
            items = [q for q in items if q.difficulty_level == difficulty_level]
        if active_only:
            items = [q for q in items if q.is_active]
        items = sorted(items, key=lambda q: q.id)
        if offset > 0:
            items = items[offset:]
        if limit is not None:
            items = items[:limit]
        return items

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
    ) -> tuple[SimpleNamespace, list[SimpleNamespace]]:
        self.mutation_calls += 1
        if self._fail_on_create:
            raise RuntimeError("DB failure during create")
        now = datetime.now(timezone.utc)
        qid = self._next_q_id
        self._next_q_id += 1
        q = SimpleNamespace(
            id=qid,
            course_id=course_id,
            learning_outcome_id=learning_outcome_id,
            question_text=question_text,
            question_type=question_type,
            difficulty_level=difficulty_level,
            points=points,
            is_active=True,
            archived_at=None,
            version_number=1,
            root_question_id=None,
            previous_version_id=None,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        opts = []
        for draft in options:
            oid = self._next_opt_id
            self._next_opt_id += 1
            opts.append(
                SimpleNamespace(
                    id=oid,
                    question_id=qid,
                    option_text=draft.option_text,
                    is_correct=draft.is_correct,
                    order_index=draft.order_index,
                )
            )
        self._questions[qid] = q
        self._options[qid] = opts
        return q, opts

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
    ) -> tuple[SimpleNamespace, list[SimpleNamespace], bool]:
        self.mutation_calls += 1
        target = self.get_by_id_for_course(question_id, course_id)
        if target is None:
            raise QuestionNotFoundError(str(question_id))
        if question_id not in self._used:
            target.learning_outcome_id = learning_outcome_id
            target.question_text = question_text
            target.difficulty_level = difficulty_level
            target.points = points
            opts = [
                SimpleNamespace(
                    id=self._next_opt_id + idx,
                    question_id=target.id,
                    option_text=d.option_text,
                    is_correct=d.is_correct,
                    order_index=d.order_index,
                )
                for idx, d in enumerate(options)
            ]
            self._next_opt_id += len(opts)
            self._options[target.id] = opts
            return target, opts, False

        target.is_active = False
        target.archived_at = datetime.now(timezone.utc)
        new_q, new_opts = self.create_with_options(
            course_id=course_id,
            learning_outcome_id=learning_outcome_id,
            question_text=question_text,
            options=options,
            question_type=question_type,
            difficulty_level=difficulty_level,
            points=points,
            created_by=updated_by,
        )
        new_q.version_number = target.version_number + 1
        new_q.root_question_id = target.root_question_id or target.id
        new_q.previous_version_id = target.id
        return new_q, new_opts, True

    def delete_or_archive(self, *, course_id: int, question_id: int) -> bool:
        self.mutation_calls += 1
        target = self.get_by_id_for_course(question_id, course_id)
        if target is None:
            raise QuestionNotFoundError(str(question_id))
        if question_id in self._used:
            target.is_active = False
            target.archived_at = datetime.now(timezone.utc)
            return True
        del self._questions[question_id]
        self._options.pop(question_id, None)
        return False


def _build_service(
    *, fail_on_create: bool = False
) -> tuple[QuestionBankService, _FakeQuestionRepo, _FakeTxManager]:
    policy = CourseAccessPolicy(
        course_repository=_FakeCourseRepo(
            {
                10: _make_course(10, instructor_id=2),
                20: _make_course(20, instructor_id=3),
            }
        ),
        enrollment_repository=_FakeEnrollmentRepo({(1, 10)}),
    )
    q_repo = _FakeQuestionRepo(fail_on_create=fail_on_create)
    lo_repo = _FakeOutcomeRepo({100: 10, 200: 20})
    tx = _FakeTxManager()
    service = QuestionBankService(
        access_policy=policy,
        question_repository=q_repo,  # type: ignore[arg-type]
        learning_outcome_repository=lo_repo,  # type: ignore[arg-type]
        transaction_manager=tx,
    )
    return service, q_repo, tx


# --- Schema Validation Tests ---


def test_schema_rejects_blank_text_invalid_options_difficulty_points_and_extra_fields() -> None:
    # Blank question_text
    with pytest.raises(ValidationError):
        QuestionCreateRequest(
            learning_outcome_id=100,
            question_text="   ",
            options=_valid_options(0),
        )

    # Blank option text
    bad_opts = _valid_options(0)
    bad_opts[1]["option_text"] = "   "
    with pytest.raises(ValidationError):
        QuestionCreateRequest(
            learning_outcome_id=100, question_text="Q?", options=bad_opts
        )

    # Wrong option count (3 instead of 4)
    with pytest.raises(ValidationError):
        QuestionCreateRequest(
            learning_outcome_id=100,
            question_text="Q?",
            options=_valid_options(0)[:3],
        )

    # Zero correct options
    zero_correct = [
        {"option_text": f"C{i}", "is_correct": False, "order_index": i}
        for i in range(4)
    ]
    with pytest.raises(ValidationError):
        QuestionCreateRequest(
            learning_outcome_id=100, question_text="Q?", options=zero_correct
        )

    # Multiple correct options
    two_correct = _valid_options(0)
    two_correct[1]["is_correct"] = True
    with pytest.raises(ValidationError):
        QuestionCreateRequest(
            learning_outcome_id=100, question_text="Q?", options=two_correct
        )

    # Duplicate order_index
    dup_order = _valid_options(0)
    dup_order[3]["order_index"] = 0
    with pytest.raises(ValidationError):
        QuestionCreateRequest(
            learning_outcome_id=100, question_text="Q?", options=dup_order
        )

    # Invalid difficulty & invalid points (<=0, NaN, inf, bool)
    with pytest.raises(ValidationError):
        QuestionCreateRequest(
            learning_outcome_id=100,
            question_text="Q?",
            difficulty_level="extreme",  # type: ignore[arg-type]
            options=_valid_options(0),
        )
    for bad_points in (0, -1.5, float("nan"), float("inf"), True):
        with pytest.raises(ValidationError):
            QuestionCreateRequest(
                learning_outcome_id=100,
                question_text="Q?",
                points=bad_points,  # type: ignore[arg-type]
                options=_valid_options(0),
            )

    # Server-managed fields rejected by extra="forbid"
    for forbidden in (
        {"created_by": 99},
        {"course_id": 10},
        {"version_number": 5},
        {"root_question_id": 1},
        {"is_active": False},
    ):
        with pytest.raises(ValidationError):
            QuestionCreateRequest(
                learning_outcome_id=100,
                question_text="Q?",
                options=_valid_options(0),
                **forbidden,  # type: ignore[arg-type]
            )


def test_student_response_schema_never_exposes_correct_answer_fields() -> None:
    forbidden_keys = {"is_correct", "answer", "correct_option_id"}
    assert not (forbidden_keys & set(QuestionStudentResponse.model_fields))
    assert not (forbidden_keys & set(QuestionStudentOptionResponse.model_fields))

    fake_q = SimpleNamespace(
        id=1,
        learning_outcome_id=100,
        question_text="2+2?",
        question_type=QuestionType.MULTIPLE_CHOICE.value,
        difficulty_level=DifficultyLevel.EASY.value,
        points=1.0,
    )
    fake_opts = [
        SimpleNamespace(id=1, option_text="4", is_correct=True, order_index=0),
        SimpleNamespace(id=2, option_text="5", is_correct=False, order_index=1),
    ]
    dumped = QuestionStudentResponse.from_models(fake_q, fake_opts).model_dump()  # type: ignore[arg-type]
    assert not (forbidden_keys & set(dumped.keys()))
    for opt in dumped["options"]:
        assert not (forbidden_keys & set(opt.keys()))


# --- Authorization & Service Behavior Tests ---


def test_authorized_instructor_and_admin_can_manage_questions() -> None:
    service, q_repo, tx = _build_service()
    owner = _make_user(2, "instructor")
    admin = _make_user(99, "admin")

    payload = QuestionCreateRequest(
        learning_outcome_id=100,
        question_text="What is O(1)?",
        difficulty_level=DifficultyLevel.EASY,
        points=2.0,
        options=_valid_options(0),
    )
    created = service.create_question(user=owner, course_id=10, payload=payload)
    assert created.course_id == 10
    assert created.created_by == 2
    assert created.points == 2.0
    assert tx.commits == 1

    listed = service.list_questions(user=admin, course_id=10)
    assert len(listed) == 1
    assert listed[0].id == created.id

    fetched = service.get_question(user=admin, course_id=10, question_id=created.id)
    assert fetched.id == created.id

    # Unused update -> in-place
    update_payload = QuestionUpdateRequest(
        learning_outcome_id=100,
        question_text="Updated O(1)",
        difficulty_level=DifficultyLevel.MEDIUM,
        points=3.0,
        options=_valid_options(1),
    )
    upd_res = service.update_question(
        user=owner, course_id=10, question_id=created.id, payload=update_payload
    )
    assert upd_res.was_versioned is False
    assert upd_res.previous_question_id is None
    assert upd_res.question.id == created.id

    # Mark used -> update creates new version
    q_repo.mark_used(created.id)
    ver_res = service.update_question(
        user=admin, course_id=10, question_id=created.id, payload=update_payload
    )
    assert ver_res.was_versioned is True
    assert ver_res.previous_question_id == created.id
    assert ver_res.question.id != created.id
    assert ver_res.question.version_number == 2

    # Delete used -> archived=True; delete unused v2 -> archived=False
    del_used = service.delete_question(user=owner, course_id=10, question_id=created.id)
    assert del_used.archived is True
    del_unused = service.delete_question(
        user=owner, course_id=10, question_id=ver_res.question.id
    )
    assert del_unused.archived is False


def test_student_other_instructor_and_inactive_user_are_denied_with_zero_mutations() -> None:
    service, q_repo, tx = _build_service()
    student = _make_user(1, "student")
    other_instructor = _make_user(3, "instructor")
    inactive_instructor = _make_user(2, "instructor", is_active=False)

    payload = QuestionCreateRequest(
        learning_outcome_id=100, question_text="Q?", options=_valid_options(0)
    )
    upd = QuestionUpdateRequest(
        learning_outcome_id=100, question_text="Q2?", options=_valid_options(1)
    )

    # Student -> RoleAuthorizationError on all 5 operations
    with pytest.raises(RoleAuthorizationError):
        service.list_questions(user=student, course_id=10)
    with pytest.raises(RoleAuthorizationError):
        service.get_question(user=student, course_id=10, question_id=1)
    with pytest.raises(RoleAuthorizationError):
        service.create_question(user=student, course_id=10, payload=payload)
    with pytest.raises(RoleAuthorizationError):
        service.update_question(user=student, course_id=10, question_id=1, payload=upd)
    with pytest.raises(RoleAuthorizationError):
        service.delete_question(user=student, course_id=10, question_id=1)

    # Other instructor & inactive user -> non-disclosing ResourceNotFoundError
    for actor in (other_instructor, inactive_instructor):
        with pytest.raises(ResourceNotFoundError):
            service.list_questions(user=actor, course_id=10)
        with pytest.raises(ResourceNotFoundError):
            service.create_question(user=actor, course_id=10, payload=payload)
        with pytest.raises(ResourceNotFoundError):
            service.update_question(user=actor, course_id=10, question_id=1, payload=upd)
        with pytest.raises(ResourceNotFoundError):
            service.delete_question(user=actor, course_id=10, question_id=1)

    assert q_repo.mutation_calls == 0
    assert tx.commits == 0


def test_cross_course_outcome_and_transaction_rollback() -> None:
    service, _, tx = _build_service()
    owner = _make_user(2, "instructor")

    bad_payload = QuestionCreateRequest(
        learning_outcome_id=200,  # belongs to course 20, not 10
        question_text="Cross course",
        options=_valid_options(0),
    )
    with pytest.raises(CrossCourseReferenceError):
        service.create_question(user=owner, course_id=10, payload=bad_payload)
    assert tx.commits == 0
    assert tx.rollbacks == 1

    # Simulated DB failure triggers rollback
    failing_service, _, fail_tx = _build_service(fail_on_create=True)
    ok_payload = QuestionCreateRequest(
        learning_outcome_id=100,
        question_text="Will fail",
        options=_valid_options(0),
    )
    with pytest.raises(RuntimeError):
        failing_service.create_question(user=owner, course_id=10, payload=ok_payload)
    assert fail_tx.commits == 0
    assert fail_tx.rollbacks == 1
