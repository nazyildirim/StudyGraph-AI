"""Self-service user profile HTTP router (`/users/me`)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies.auth import get_current_user, get_user_profile_service
from app.api.routing import SanitizedValidationRoute
from app.models.user import User
from app.repositories.user_repository import UserNotFoundError
from app.schemas.user import ProfileUpdateRequest, UserResponse
from app.services.user_profile_service import UserProfileService

router = APIRouter(
    prefix="/users",
    tags=["Users"],
    route_class=SanitizedValidationRoute,
)


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
)
def get_my_profile(
    current_user: User = Depends(get_current_user),
    profile_service: UserProfileService = Depends(get_user_profile_service),
) -> UserResponse:
    """Return the authenticated user's profile."""
    return UserResponse.model_validate(profile_service.get_profile(current_user))


@router.patch(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
)
def update_my_profile(
    payload: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    profile_service: UserProfileService = Depends(get_user_profile_service),
) -> UserResponse:
    """Update allowlisted profile fields (`first_name`, `last_name`) only."""
    try:
        updated = profile_service.update_profile(
            current_user,
            first_name=payload.first_name,
            last_name=payload.last_name,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except UserNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error

    return UserResponse.model_validate(updated)
