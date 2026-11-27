"""Stateless API tests for Issue #7 routers, error mapping, OpenAPI, and wiring."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
import pytest

from app.api.dependencies.assessment import (
    get_exam_generation_service,
    get_exam_submission_service,
    get_mastery_query_service,
    get_question_bank_service,
    translate_assessment_error,
)
from app.api.dependencies.auth import get_current_user
from app.authorization.ownership import ResourceNotFoundError, RoleAuthorizationError
from app.core.config import Settings
from app.main import app
from app.repositories.errors import (
    AttemptAlreadyFinalizedError,
    CrossCourseReferenceError,
    DuplicateResponseError,
    InvalidQuestionOptionsError,
    InvalidResponseError,
    PaginationValidationError,
    QuestionArchivedError,
)
from app.schemas.exam import (
    ExamHistoryItemResponse,
    ExamResultResponse,
    StudentExamOptionResponse,
    StudentExamQuestionResponse,
    StudentExamResponse,
)
from app.schemas.mastery import (
    CourseMasteryMapResponse,
    CourseOutcomeResponse,
    CourseRecommendationsResponse,
)
from app.services.exam_generation_service import (
    ActiveRetestConflictError,
    DiagnosticExamAlreadyCompletedError,
    DiagnosticExamRequiredError,
    InsufficientQuestionsError,
    NoEligibleOutcomesForRetestError,
    OutcomeNotEligibleForRetestError,
)
from app.services.exam_submission_service import AttemptNotCompletedError
from app.services.learning_analysis_service import LearningAnalysisService
from app.services.mastery_integration import MasteryIntegrationAdapter


def _clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_openapi_registers_all_issue7_canonical_routes_without_conflicts() -> None:
    schema = app.openapi()
    paths = set(schema["paths"].keys())
    expected = {
        "/api/v1/courses/{course_id}/questions",
        "/api/v1/courses/{course_id}/questions/{question_id}",
        "/api/v1/courses/{course_id}/exams/initial",
        "/api/v1/courses/{course_id}/exams/retest",
        "/api/v1/courses/{course_id}/exams/attempts/{attempt_id}",
        "/api/v1/courses/{course_id}/exams/attempts/{attempt_id}/submit",
        "/api/v1/courses/{course_id}/exams/attempts/{attempt_id}/result",
        "/api/v1/courses/{course_id}/exams/history",
        "/api/v1/courses/{course_id}/outcomes",
        "/api/v1/courses/{course_id}/mastery",
        "/api/v1/courses/{course_id}/recommendations",
    }
    assert expected <= paths
    # Existing routes preserved
    assert "/api/v1/health" in paths
    assert "/api/v1/learning-analyses" in paths
    assert "/api/v1/auth/login" in paths


def test_production_dependency_wiring_injects_real_mastery_integrator() -> None:
    fake_session = MagicMock()
    svc = get_exam_submission_service(
        db=fake_session, settings=Settings(_env_file=None)
    )
    assert isinstance(svc._mastery_integrator, MasteryIntegrationAdapter)
    assert isinstance(svc._mastery_integrator._analysis, LearningAnalysisService)


def test_http_error_translation_covers_all_domain_errors_and_anti_enumeration() -> None:
    assert translate_assessment_error(RoleAuthorizationError("x")).status_code == 403
    for err in (
        ResourceNotFoundError("x"),
        CrossCourseReferenceError("secret course 99"),
    ):
        exc = translate_assessment_error(err)
        assert exc.status_code == 404
        assert exc.detail == "Resource not found."

    for err in (
        InsufficientQuestionsError("no q"),
        DiagnosticExamAlreadyCompletedError("done"),
        DiagnosticExamRequiredError("need diag"),
        NoEligibleOutcomesForRetestError("none"),
        OutcomeNotEligibleForRetestError("blocked"),
        ActiveRetestConflictError("active"),
        AttemptAlreadyFinalizedError("final"),
        AttemptNotCompletedError("in progress"),
        QuestionArchivedError("archived"),
    ):
        assert translate_assessment_error(err).status_code == 409

    for err in (
        InvalidResponseError("bad"),
        DuplicateResponseError("dup"),
        InvalidQuestionOptionsError("opts"),
        PaginationValidationError("limit out of bounds"),
    ):
        assert translate_assessment_error(err).status_code == 422

    # Unexpected ValueError must NOT be disguised as client 422 -> maps to 500
    internal_exc = translate_assessment_error(ValueError("internal secret details"))
    assert internal_exc.status_code == 500
    assert internal_exc.detail == "Internal server error."


def test_unauthenticated_requests_return_401_and_validation_errors_are_sanitized() -> None:
    _clear_overrides()
    client = TestClient(app)

    for method, url in (
        ("GET", "/api/v1/courses/1/questions"),
        ("POST", "/api/v1/courses/1/exams/initial"),
        ("POST", "/api/v1/courses/1/exams/retest"),
        ("GET", "/api/v1/courses/1/outcomes"),
        ("GET", "/api/v1/courses/1/mastery"),
        ("GET", "/api/v1/courses/1/recommendations"),
    ):
        resp = client.request(method, url)
        assert resp.status_code == 401

    # Invalid JWT returns 401
    resp_bad_jwt = client.get(
        "/api/v1/courses/1/questions",
        headers={"Authorization": "Bearer not.a.valid.jwt"},
    )
    assert resp_bad_jwt.status_code == 401

    # Sanitized 422: raw invalid input is NOT echoed back
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=2, role="instructor", is_active=True
    )
    app.dependency_overrides[get_question_bank_service] = lambda: MagicMock()
    try:
        resp_422 = client.post(
            "/api/v1/courses/1/questions",
            json={
                "learning_outcome_id": 1,
                "question_text": "   ",
                "options": [],
                "created_by": 999,
            },
        )
        assert resp_422.status_code == 422
        assert "999" not in resp_422.text
    finally:
        _clear_overrides()


def test_exam_endpoints_return_201_on_create_200_on_resume_and_hide_answers() -> None:
    now = datetime(2026, 11, 28, 0, 0, tzinfo=timezone.utc)
    base_exam = StudentExamResponse(
        attempt_id=42,
        assessment_id=7,
        course_id=1,
        assessment_type="diagnostic",
        status="in_progress",
        requested_count=15,
        actual_count=1,
        uncovered_outcome_ids=[],
        resumed=False,
        started_at=now,
        questions=[
            StudentExamQuestionResponse(
                question_id=10,
                learning_outcome_id=1,
                question_text="Q1?",
                difficulty_level="medium",
                order_index=0,
                options=[
                    StudentExamOptionResponse(
                        option_id=100, option_text="A", order_index=0
                    )
                ],
            )
        ],
    )
    resumed_exam = base_exam.model_copy(update={"resumed": True})

    fake_gen = MagicMock()
    fake_gen.start_initial_exam.side_effect = [base_exam, resumed_exam]
    fake_gen.get_student_exam.return_value = base_exam
    fake_sub = MagicMock()
    fake_sub.list_exam_history.return_value = [
        ExamHistoryItemResponse(
            attempt_id=42,
            assessment_id=7,
            course_id=1,
            assessment_type="diagnostic",
            title="Initial Diagnostic Exam",
            status="in_progress",
            score=None,
            started_at=now,
            completed_at=None,
        )
    ]
    fake_query = MagicMock()
    fake_query.list_course_outcomes.return_value = [
        CourseOutcomeResponse(
            id=1, course_id=1, code="LO-1", title="Basics", order_index=0
        )
    ]
    fake_query.get_student_mastery_map.return_value = CourseMasteryMapResponse(
        course_id=1, mastery_threshold=70.0, outcomes=[]
    )
    fake_query.get_student_recommendations.return_value = CourseRecommendationsResponse(
        course_id=1, mastery_threshold=70.0, recommendations=[]
    )

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, role="student", is_active=True
    )
    app.dependency_overrides[get_exam_generation_service] = lambda: fake_gen
    app.dependency_overrides[get_exam_submission_service] = lambda: fake_sub
    app.dependency_overrides[get_mastery_query_service] = lambda: fake_query
    try:
        client = TestClient(app)
        r_create = client.post("/api/v1/courses/1/exams/initial")
        assert r_create.status_code == 201
        assert "is_correct" not in r_create.text
        assert "correct_option_id" not in r_create.text

        r_resume = client.post("/api/v1/courses/1/exams/initial")
        assert r_resume.status_code == 200
        assert r_resume.json()["attempt_id"] == 42

        assert client.get("/api/v1/courses/1/exams/attempts/42").status_code == 200
        assert client.get("/api/v1/courses/1/exams/history").status_code == 200
        assert client.get("/api/v1/courses/1/outcomes").status_code == 200
        assert client.get("/api/v1/courses/1/mastery").status_code == 200
        assert client.get("/api/v1/courses/1/recommendations").status_code == 200
    finally:
        _clear_overrides()
