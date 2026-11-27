"""Canonical `/api/v1` Student Exam endpoints (initial, retest, submit, history)."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Path, Query, Response, status

from app.api.dependencies.assessment import (
    get_exam_generation_service,
    get_exam_submission_service,
    translate_assessment_error,
)
from app.api.dependencies.auth import get_current_user
from app.api.routing import SanitizedValidationRoute
from app.core.security.tokens import MAX_PG_INT32, MIN_USER_ID
from app.models.user import User
from app.schemas.exam import (
    ExamHistoryItemResponse,
    ExamResultResponse,
    ExamSubmitRequest,
    InitialExamCreateRequest,
    RetestExamCreateRequest,
    StudentExamResponse,
)
from app.services.exam_generation_service import ExamGenerationService
from app.services.exam_submission_service import ExamSubmissionService

router = APIRouter(
    tags=["Exams"],
    route_class=SanitizedValidationRoute,
)


@router.post(
    "/courses/{course_id}/exams/initial",
    response_model=StudentExamResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_200_OK: {"model": StudentExamResponse}},
)
def start_initial_exam(
    response: Response,
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    payload: InitialExamCreateRequest | None = Body(default=None),
    current_user: User = Depends(get_current_user),
    service: ExamGenerationService = Depends(get_exam_generation_service),
) -> StudentExamResponse:
    try:
        result = service.start_initial_exam(
            user=current_user,
            course_id=course_id,
            payload=payload,
        )
    except Exception as error:
        raise translate_assessment_error(error) from error
    response.status_code = (
        status.HTTP_200_OK if result.resumed else status.HTTP_201_CREATED
    )
    return result


@router.post(
    "/courses/{course_id}/exams/retest",
    response_model=StudentExamResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_200_OK: {"model": StudentExamResponse}},
)
def start_retest_exam(
    response: Response,
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    payload: RetestExamCreateRequest | None = Body(default=None),
    current_user: User = Depends(get_current_user),
    service: ExamGenerationService = Depends(get_exam_generation_service),
) -> StudentExamResponse:
    try:
        result = service.start_retest_exam(
            user=current_user,
            course_id=course_id,
            payload=payload,
        )
    except Exception as error:
        raise translate_assessment_error(error) from error
    response.status_code = (
        status.HTTP_200_OK if result.resumed else status.HTTP_201_CREATED
    )
    return result


@router.get(
    "/courses/{course_id}/exams/attempts/{attempt_id}",
    response_model=StudentExamResponse,
    status_code=status.HTTP_200_OK,
)
def get_exam_attempt(
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    attempt_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    current_user: User = Depends(get_current_user),
    service: ExamGenerationService = Depends(get_exam_generation_service),
) -> StudentExamResponse:
    try:
        return service.get_student_exam(
            user=current_user,
            course_id=course_id,
            attempt_id=attempt_id,
        )
    except Exception as error:
        raise translate_assessment_error(error) from error


@router.post(
    "/courses/{course_id}/exams/attempts/{attempt_id}/submit",
    response_model=ExamResultResponse,
    status_code=status.HTTP_200_OK,
)
def submit_exam_attempt(
    payload: ExamSubmitRequest,
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    attempt_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    current_user: User = Depends(get_current_user),
    service: ExamSubmissionService = Depends(get_exam_submission_service),
) -> ExamResultResponse:
    try:
        return service.submit_exam(
            user=current_user,
            course_id=course_id,
            attempt_id=attempt_id,
            payload=payload,
        )
    except Exception as error:
        raise translate_assessment_error(error) from error


@router.get(
    "/courses/{course_id}/exams/attempts/{attempt_id}/result",
    response_model=ExamResultResponse,
    status_code=status.HTTP_200_OK,
)
def get_exam_attempt_result(
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    attempt_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    current_user: User = Depends(get_current_user),
    service: ExamSubmissionService = Depends(get_exam_submission_service),
) -> ExamResultResponse:
    try:
        return service.get_exam_result(
            user=current_user,
            course_id=course_id,
            attempt_id=attempt_id,
        )
    except Exception as error:
        raise translate_assessment_error(error) from error


@router.get(
    "/courses/{course_id}/exams/history",
    response_model=list[ExamHistoryItemResponse],
    status_code=status.HTTP_200_OK,
)
def list_exam_history(
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    service: ExamSubmissionService = Depends(get_exam_submission_service),
) -> list[ExamHistoryItemResponse]:
    try:
        return service.list_exam_history(
            user=current_user,
            course_id=course_id,
            limit=limit,
            offset=offset,
        )
    except Exception as error:
        raise translate_assessment_error(error) from error
