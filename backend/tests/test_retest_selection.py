"""Stateless unit tests for retest question selection, schemas, and guardrails."""

from __future__ import annotations

import random
from types import SimpleNamespace

from pydantic import ValidationError
import pytest

from app.models.question import DifficultyLevel, QuestionType
from app.schemas.exam import RetestExamCreateRequest
from app.services.exam_generation_service import select_retest_questions
from app.services.exam_submission_service import ExamSubmissionService


def _q(
    qid: int,
    outcome_id: int,
    *,
    difficulty: str = DifficultyLevel.MEDIUM.value,
    is_active: bool = True,
    version_number: int = 1,
    root_question_id: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=qid,
        course_id=10,
        learning_outcome_id=outcome_id,
        question_text=f"Q{qid}",
        question_type=QuestionType.MULTIPLE_CHOICE.value,
        difficulty_level=difficulty,
        points=1.0,
        is_active=is_active,
        version_number=version_number,
        root_question_id=root_question_id,
    )


def test_retest_prioritizes_unseen_then_fills_with_seen_without_duplicates() -> None:
    # 3 unseen (1,2,3) + 10 seen (10..19) -> requested 5 => 3 unseen + 2 seen
    pool = [_q(i, 100) for i in (1, 2, 3)] + [_q(i, 100) for i in range(10, 20)]
    seen = set(range(10, 20))

    sel = select_retest_questions(
        targeted_outcome_ids=[100],
        active_questions=pool,  # type: ignore[arg-type]
        seen_lineage_ids=seen,
        requested_count=5,
        rng=random.Random(42),
    )
    assert sel.requested_count == 5
    assert sel.actual_count == 5
    assert sel.unseen_question_count == 3
    assert sel.reused_question_count == 2
    assert sel.unseen_question_count + sel.reused_question_count == sel.actual_count
    assert {q.id for q in sel.questions[:3]} == {1, 2, 3}
    assert all(q.id in seen for q in sel.questions[3:])
    assert len({q.id for q in sel.questions}) == 5


def test_retest_picks_only_unseen_when_sufficient_and_respects_lineage_versions() -> None:
    # q10 is v2 of root 1 (which is in seen_lineage_ids!) -> must be treated as SEEN!
    pool = [
        _q(2, 100),
        _q(3, 100),
        _q(4, 101),
        _q(5, 101),
        _q(6, 101),
        _q(10, 100, version_number=2, root_question_id=1),  # seen lineage!
        _q(11, 100, is_active=False),  # archived -> excluded!
    ]
    sel = select_retest_questions(
        targeted_outcome_ids=[100, 101],
        active_questions=pool,  # type: ignore[arg-type]
        seen_lineage_ids={1},
        requested_count=5,
        rng=random.Random(7),
    )
    assert sel.actual_count == 5
    assert sel.unseen_question_count == 5
    assert sel.reused_question_count == 0
    assert 10 not in {q.id for q in sel.questions}
    assert 11 not in {q.id for q in sel.questions}
    assert sel.covered_outcome_ids == (100, 101)
    assert sel.uncovered_outcome_ids == ()


def test_retest_difficulty_filter_is_strict_and_insufficient_pool_never_repeats() -> None:
    pool = [
        _q(1, 100, difficulty="easy"),
        _q(2, 100, difficulty="hard"),
        _q(3, 100, difficulty="hard"),
    ]
    # Strict hard filter: only 2 hard questions exist, must NOT pull easy q1
    sel = select_retest_questions(
        targeted_outcome_ids=[100],
        active_questions=pool,  # type: ignore[arg-type]
        seen_lineage_ids=set(),
        requested_count=5,
        difficulty=DifficultyLevel.HARD,
        rng=random.Random(1),
    )
    assert sel.requested_count == 5
    assert sel.actual_count == 2
    assert {q.id for q in sel.questions} == {2, 3}


def test_retest_request_schema_forbids_server_fields_and_invalid_difficulty() -> None:
    for forbidden in (
        {"student_id": 1},
        {"mastery_score": 80.0},
        {"is_correct": True},
        {"score": 100.0},
        {"assessment_type": "diagnostic"},
        {"mastery_threshold": 50.0},
        {"difficulty": "impossible"},
        {"question_count": True},
        {"learning_outcome_id": False},
    ):
        with pytest.raises(ValidationError):
            RetestExamCreateRequest(**forbidden)  # type: ignore[arg-type]


def test_exam_submission_service_requires_mastery_integrator_by_default() -> None:
    with pytest.raises(ValueError, match="mastery_integrator is required"):
        ExamSubmissionService(
            access_policy=SimpleNamespace(),  # type: ignore[arg-type]
            assessment_repository=SimpleNamespace(),  # type: ignore[arg-type]
            question_repository=SimpleNamespace(),  # type: ignore[arg-type]
            mastery_repository=SimpleNamespace(),  # type: ignore[arg-type]
            transaction_manager=SimpleNamespace(),  # type: ignore[arg-type]
        )
