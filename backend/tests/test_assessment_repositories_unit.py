"""Stateless unit tests for Issue #7 repository validators and lock key helpers."""

from __future__ import annotations

import pytest

from app.repositories import (
    AssessmentRepository,
    LearningOutcomeRepository,
    MasteryRepository,
    QuestionOptionDraft,
    QuestionRepository,
    SqlAlchemyAssessmentRepository,
    SqlAlchemyLearningOutcomeRepository,
    SqlAlchemyMasteryRepository,
    SqlAlchemyQuestionRepository,
)
from app.repositories.errors import InvalidQuestionOptionsError
from app.repositories.mastery_repository import build_student_course_lock_key
from app.repositories.question_repository import validate_question_options


def test_validate_question_options_accepts_exactly_one_correct_option() -> None:
    validate_question_options(
        [
            QuestionOptionDraft("A", True, 0),
            QuestionOptionDraft("B", False, 1),
            QuestionOptionDraft("C", False, 2),
            QuestionOptionDraft("D", False, 3),
        ]
    )


def test_validate_question_options_rejects_zero_or_multiple_correct_options() -> None:
    with pytest.raises(InvalidQuestionOptionsError):
        validate_question_options(
            [
                QuestionOptionDraft("A", False, 0),
                QuestionOptionDraft("B", False, 1),
            ]
        )

    with pytest.raises(InvalidQuestionOptionsError):
        validate_question_options(
            [
                QuestionOptionDraft("A", True, 0),
                QuestionOptionDraft("B", True, 1),
            ]
        )


def test_validate_question_options_rejects_too_few_duplicate_or_blank_options() -> None:
    with pytest.raises(InvalidQuestionOptionsError):
        validate_question_options([QuestionOptionDraft("Only one", True, 0)])

    with pytest.raises(InvalidQuestionOptionsError):
        validate_question_options(
            [
                QuestionOptionDraft("A", True, 0),
                QuestionOptionDraft("B", False, 0),
            ]
        )

    with pytest.raises(InvalidQuestionOptionsError):
        validate_question_options(
            [
                QuestionOptionDraft("A", True, -1),
                QuestionOptionDraft("B", False, 0),
            ]
        )

    with pytest.raises(InvalidQuestionOptionsError):
        validate_question_options(
            [
                QuestionOptionDraft("   ", True, 0),
                QuestionOptionDraft("B", False, 1),
            ]
        )


def test_student_course_lock_key_is_deterministic_and_collision_free() -> None:
    k1 = build_student_course_lock_key(student_id=1, course_id=2)
    k2 = build_student_course_lock_key(student_id=2, course_id=1)
    assert k1 != k2
    assert k1 == build_student_course_lock_key(student_id=1, course_id=2)

    with pytest.raises(ValueError):
        build_student_course_lock_key(student_id=0, course_id=1)
    with pytest.raises(ValueError):
        build_student_course_lock_key(student_id=1, course_id=-5)


def test_repository_exports_are_importable_without_env() -> None:
    assert LearningOutcomeRepository is not None
    assert QuestionRepository is not None
    assert AssessmentRepository is not None
    assert MasteryRepository is not None
    assert SqlAlchemyLearningOutcomeRepository is not None
    assert SqlAlchemyQuestionRepository is not None
    assert SqlAlchemyAssessmentRepository is not None
    assert SqlAlchemyMasteryRepository is not None
