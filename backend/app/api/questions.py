"""Canonical `/api/v1` Question Bank endpoints for instructors and admins (Issue #7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query, status

from app.api.dependencies.assessment import (
    get_question_bank_service,
    translate_assessment_error,
)
from app.api.dependencies.auth import get_current_user
from app.api.routing import SanitizedValidationRoute
from app.core.security.tokens import MAX_PG_INT32, MIN_USER_ID
from app.models.question import DifficultyLevel
from app.models.user import User
from app.schemas.question import (
    QuestionCreateRequest,
    QuestionDeleteResponse,
    QuestionInstructorResponse,
    QuestionUpdateRequest,
    QuestionUpdateResponse,
)
from app.services.question_bank_service import QuestionBankService

router = APIRouter(
    tags=["Question Bank"],
    route_class=SanitizedValidationRoute,
)


@router.get(
    "/courses/{course_id}/questions",
    response_model=list[QuestionInstructorResponse],
    status_code=status.HTTP_200_OK,
)
def list_questions(
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    learning_outcome_id: int | None = Query(
        default=None, ge=MIN_USER_ID, le=MAX_PG_INT32
    ),
    difficulty: DifficultyLevel | None = Query(default=None),
    include_archived: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    service: QuestionBankService = Depends(get_question_bank_service),
) -> list[QuestionInstructorResponse]:
    try:
        return service.list_questions(
            user=current_user,
            course_id=course_id,
            learning_outcome_id=learning_outcome_id,
            difficulty_level=difficulty.value if difficulty is not None else None,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )
    except Exception as error:
        raise translate_assessment_error(error) from error


@router.post(
    "/courses/{course_id}/questions",
    response_model=QuestionInstructorResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_question(
    payload: QuestionCreateRequest,
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    current_user: User = Depends(get_current_user),
    service: QuestionBankService = Depends(get_question_bank_service),
) -> QuestionInstructorResponse:
    try:
        return service.create_question(
            user=current_user,
            course_id=course_id,
            payload=payload,
        )
    except Exception as error:
        raise translate_assessment_error(error) from error


@router.get(
    "/courses/{course_id}/questions/{question_id}",
    response_model=QuestionInstructorResponse,
    status_code=status.HTTP_200_OK,
)
def get_question(
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    question_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    current_user: User = Depends(get_current_user),
    service: QuestionBankService = Depends(get_question_bank_service),
) -> QuestionInstructorResponse:
    try:
        return service.get_question(
            user=current_user,
            course_id=course_id,
            question_id=question_id,
        )
    except Exception as error:
        raise translate_assessment_error(error) from error


@router.put(
    "/courses/{course_id}/questions/{question_id}",
    response_model=QuestionUpdateResponse,
    status_code=status.HTTP_200_OK,
)
def update_question(
    payload: QuestionUpdateRequest,
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    question_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    current_user: User = Depends(get_current_user),
    service: QuestionBankService = Depends(get_question_bank_service),
) -> QuestionUpdateResponse:
    try:
        return service.update_question(
            user=current_user,
            course_id=course_id,
            question_id=question_id,
            payload=payload,
        )
    except Exception as error:
        raise translate_assessment_error(error) from error


@router.delete(
    "/courses/{course_id}/questions/{question_id}",
    response_model=QuestionDeleteResponse,
    status_code=status.HTTP_200_OK,
)
def delete_question(
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    question_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    current_user: User = Depends(get_current_user),
    service: QuestionBankService = Depends(get_question_bank_service),
) -> QuestionDeleteResponse:
    try:
        return service.delete_question(
            user=current_user,
            course_id=course_id,
            question_id=question_id,
        )
    except Exception as error:
        raise translate_assessment_error(error) from error
