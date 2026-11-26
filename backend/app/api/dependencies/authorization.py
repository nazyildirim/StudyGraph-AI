"""FastAPI authorization dependencies (`require_roles` and `require_resource_access`).

Separated from authentication (`get_current_user`) so identity verification
and access-control enforcement remain decoupled (SRP/DIP).
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Path, status

from app.api.dependencies.auth import get_current_user
from app.authorization.ownership import (
    DEFAULT_BYPASS_ROLES,
    OwnershipPolicy,
    ResourceNotFoundError,
    ResourceOwnerResolver,
    RoleAuthorizationError,
    check_role_access,
)
from app.authorization.roles import Role
from app.core.security.tokens import MAX_PG_INT32, MIN_USER_ID
from app.models.user import User


def require_roles(*allowed_roles: Role) -> Callable[..., User]:
    """Dependency factory enforcing deny-by-default role authorization (403)."""
    allowed = frozenset(allowed_roles)

    def _role_dependency(
        current_user: User = Depends(get_current_user),
    ) -> User:
        try:
            check_role_access(current_user, allowed)
        except RoleAuthorizationError as error:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(error),
            ) from error
        return current_user

    return _role_dependency


def require_resource_access(
    resolver_dependency: Callable[..., ResourceOwnerResolver],
    *,
    bypass_roles: frozenset[Role] = DEFAULT_BYPASS_ROLES,
    policy: OwnershipPolicy | None = None,
) -> Callable[..., User]:
    """Dependency factory enforcing non-disclosing resource ownership (404).

    Routes using this dependency must declare a `{resource_id}` path parameter.
    """
    active_policy = policy or OwnershipPolicy()
    allowed_bypass = frozenset(bypass_roles)

    def _resource_access_dependency(
        resource_id: int = Path(ge=MIN_USER_ID, le=MAX_PG_INT32),
        current_user: User = Depends(get_current_user),
        resolver: ResourceOwnerResolver = Depends(resolver_dependency),
    ) -> User:
        owner_id = resolver.get_owner_id(resource_id)
        try:
            active_policy.check(
                current_user,
                owner_id,
                bypass_roles=allowed_bypass,
            )
        except ResourceNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error
        return current_user

    return _resource_access_dependency


__all__ = ["require_roles", "require_resource_access"]
