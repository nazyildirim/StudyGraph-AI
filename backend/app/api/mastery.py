"""Canonical `/api/v1` read-only Student Mastery & Recommendations endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, status

from app.api.dependencies.assessment import (
    get_mastery_query_service,
    translate_assessment_error,
)
from app.api.dependencies.auth import get_current_user
from app.api.routing import SanitizedValidationRoute
from app.core.security.tokens import MAX_PG_INT32, MIN_USER_ID
from app.models.user import User
from app.schemas.mastery import (
    CourseMasteryMapResponse,
    CourseRecommendationsResponse,
)
from app.services.mastery_query_service import MasteryQueryService

router = APIRouter(
    tags=["Mastery & Recommendations"],
    route_class=SanitizedValidationRoute,
)


@router.get(
    "/courses/{course_id}/mastery",
    response_model=CourseMasteryMapResponse,
    status_code=status.HTTP_200_OK,
)
def get_course_mastery(
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    current_user: User = Depends(get_current_user),
    service: MasteryQueryService = Depends(get_mastery_query_service),
) -> CourseMasteryMapResponse:
    try:
        return service.get_student_mastery_map(
            user=current_user,
            course_id=course_id,
        )
    except Exception as error:
        raise translate_assessment_error(error) from error


@router.get(
    "/courses/{course_id}/recommendations",
    response_model=CourseRecommendationsResponse,
    status_code=status.HTTP_200_OK,
)
def get_course_recommendations(
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    current_user: User = Depends(get_current_user),
    service: MasteryQueryService = Depends(get_mastery_query_service),
) -> CourseRecommendationsResponse:
    try:
        return service.get_student_recommendations(
            user=current_user,
            course_id=course_id,
        )
    except Exception as error:
        raise translate_assessment_error(error) from error
