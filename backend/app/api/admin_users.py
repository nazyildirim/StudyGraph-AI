"""Admin user management HTTP router (`/admin/users`).

Restricted to active users with `Role.ADMIN` via `require_roles(Role.ADMIN)`.
No user creation or hard-deletion endpoints exist; deactivation is soft-disable
via `is_active = false`, protected by the last-active-admin invariant.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from app.api.dependencies.auth import get_admin_user_service
from app.api.dependencies.authorization import require_roles
from app.api.routing import SanitizedValidationRoute
from app.authorization.roles import Role
from app.core.security.tokens import MAX_PG_INT32, MIN_USER_ID
from app.repositories.user_repository import (
    LastActiveAdminError,
    UserNotFoundError,
)
from app.schemas.user import (
    AdminRoleUpdateRequest,
    AdminStatusUpdateRequest,
    AdminUserListResponse,
    UserResponse,
)
from app.services.admin_user_service import AdminUserService

router = APIRouter(
    prefix="/admin/users",
    tags=["Admin Users"],
    dependencies=[Depends(require_roles(Role.ADMIN))],
    route_class=SanitizedValidationRoute,
)


@router.get(
    "",
    response_model=AdminUserListResponse,
    status_code=status.HTTP_200_OK,
)
def list_users(
    role: Role | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    admin_service: AdminUserService = Depends(get_admin_user_service),
) -> AdminUserListResponse:
    """List users with pagination and optional role/status filtering."""
    items, total = admin_service.list_users(
        role=role,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return AdminUserListResponse(
        items=[UserResponse.model_validate(user) for user in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
)
def get_user(
    user_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    admin_service: AdminUserService = Depends(get_admin_user_service),
) -> UserResponse:
    """Retrieve a user by ID."""
    try:
        user = admin_service.get_user(user_id)
    except UserNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    return UserResponse.model_validate(user)


@router.patch(
    "/{user_id}/role",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
)
def update_user_role(
    payload: AdminRoleUpdateRequest,
    user_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    admin_service: AdminUserService = Depends(get_admin_user_service),
) -> UserResponse:
    """Update a user's role while protecting the last active admin."""
    try:
        updated = admin_service.change_role(user_id, payload.role)
    except UserNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except LastActiveAdminError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    return UserResponse.model_validate(updated)


@router.patch(
    "/{user_id}/status",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
)
def update_user_status(
    payload: AdminStatusUpdateRequest,
    user_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
    admin_service: AdminUserService = Depends(get_admin_user_service),
) -> UserResponse:
    """Activate or deactivate a user while protecting the last active admin."""
    try:
        updated = admin_service.set_active_status(user_id, payload.is_active)
    except UserNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except LastActiveAdminError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    return UserResponse.model_validate(updated)
