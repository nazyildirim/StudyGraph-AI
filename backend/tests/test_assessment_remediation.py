"""Stateless unit tests for Issue #7 Final Code Review remediation (M1, L1, L2)."""

from __future__ import annotations

import logging

import pytest

from app.api.dependencies.assessment import translate_assessment_error
from app.models.question import DifficultyLevel
from app.repositories.errors import PaginationValidationError
from app.services.exam_generation_service import (
    _decode_diagnostic_metadata,
    _decode_retest_metadata,
    _encode_diagnostic_metadata,
    _encode_retest_metadata,
)


def test_m1_and_l2_unexpected_value_error_returns_500_and_logs_safely_without_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_msg = "postgresql://user:SuperSecretPass@127.0.0.1:5432/db Bearer eyJsecret"
    with caplog.at_level(logging.ERROR):
        exc = translate_assessment_error(
            ValueError(secret_msg), operation="submit_exam"
        )

    assert exc.status_code == 500
    assert exc.detail == "Internal server error."
    assert secret_msg not in str(exc.detail)
    assert any(
        "submit_exam" in rec.message and "ValueError" in rec.message
        for rec in caplog.records
    )
    for rec in caplog.records:
        assert "SuperSecretPass" not in rec.message
        assert "eyJsecret" not in rec.message

    # Explicit domain validation error still returns 422
    val_exc = translate_assessment_error(PaginationValidationError("limit invalid"))
    assert val_exc.status_code == 422


def test_l1_strict_metadata_decoders_handle_valid_and_corrupted_payloads() -> None:
    valid_diag = _encode_diagnostic_metadata(
        requested_count=6, targeted_outcome_ids=[1, 2, 3]
    )
    decoded_diag = _decode_diagnostic_metadata(valid_diag)
    assert decoded_diag is not None
    assert decoded_diag.requested_count == 6
    assert decoded_diag.targeted_outcome_ids == [1, 2, 3]

    valid_retest = _encode_retest_metadata(
        requested_count=5,
        unseen_question_count=3,
        reused_question_count=2,
        targeted_outcome_ids=[10, 20],
        requested_outcome_id=10,
        difficulty=DifficultyLevel.MEDIUM,
    )
    decoded_retest = _decode_retest_metadata(valid_retest, actual_count=5)
    assert decoded_retest is not None
    assert decoded_retest.unseen_question_count == 3
    assert decoded_retest.reused_question_count == 2
    assert decoded_retest.difficulty is DifficultyLevel.MEDIUM

    # Mismatched actual_count rejects corrupted unseen/reused sum -> None (never fabricates)
    assert _decode_retest_metadata(valid_retest, actual_count=4) is None

    bad_payloads = [
        None,
        "",
        "Legacy plain text description",
        "{not valid json",
        "[1, 2, 3]",
        "{}",
        '{"requested_count": "abc", "targeted_outcome_ids": [1]}',
        '{"requested_count": true, "targeted_outcome_ids": [1]}',
        '{"requested_count": -5, "targeted_outcome_ids": [1]}',
        '{"requested_count": 5, "targeted_outcome_ids": [0]}',
        '{"requested_count": 5, "targeted_outcome_ids": ["x"]}',
        '{"requested_count": 5, "unseen_question_count": -1, "reused_question_count": 2, "targeted_outcome_ids": [1]}',
        '{"requested_count": 5, "unseen_question_count": 3, "reused_question_count": 2, "targeted_outcome_ids": [1], "difficulty": "extreme"}',
        '{"requested_count": 5, "unseen_question_count": true, "reused_question_count": 2, "targeted_outcome_ids": [1]}',
    ]
    for raw in bad_payloads:
        assert _decode_diagnostic_metadata(raw) is None
        assert _decode_retest_metadata(raw) is None
