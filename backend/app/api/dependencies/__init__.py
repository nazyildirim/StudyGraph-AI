"""FastAPI dependency providers (authentication and authorization)."""

from app.api.dependencies.auth import (
    get_admin_user_service,
    get_auth_service,
    get_current_user,
    get_login_rate_limiter,
    get_password_hasher,
    get_password_policy,
    get_token_service,
    get_user_profile_service,
    get_user_repository,
)
from app.api.dependencies.authorization import (
    require_resource_access,
    require_roles,
)

__all__ = [
    "get_admin_user_service",
    "get_auth_service",
    "get_current_user",
    "get_login_rate_limiter",
    "get_password_hasher",
    "get_password_policy",
    "get_token_service",
    "get_user_profile_service",
    "get_user_repository",
    "require_resource_access",
    "require_roles",
]
