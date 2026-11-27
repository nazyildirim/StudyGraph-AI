"""Canonical `/api/v1` read-only Course Learning Outcomes endpoint (Issue #7)."""

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
from app.schemas.mastery import CourseOutcomeResponse
from app.services.mastery_query_service import MasteryQueryService

router = APIRouter(
    tags=["Learning Outcomes"],
    route_class=SanitizedValidationRoute,
)


@router.get(
    "/courses/{course_id}/outcomes",
    response_model=list[CourseOutcomeResponse],
    status_code=status.HTTP_200_OK,
)
def list_course_outcomes(
    course_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    current_user: User = Depends(get_current_user),
    service: MasteryQueryService = Depends(get_mastery_query_service),
) -> list[CourseOutcomeResponse]:
    try:
        return service.list_course_outcomes(
            user=current_user,
            course_id=course_id,
        )
    except Exception as error:
        raise translate_assessment_error(error) from error
