"""Lazy FastAPI dependency providers for authentication services.

No settings, secrets, or database connections are loaded at module import time.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.authorization.ownership import parse_user_role
from app.core.config import get_settings
from app.core.security.passwords import (
    Argon2PasswordHasher,
    PasswordHasher,
    PasswordPolicy,
)
from app.core.security.rate_limit import (
    InMemoryLoginRateLimiter,
    LoginRateLimiter,
)
from app.core.security.tokens import (
    JwtTokenService,
    TokenError,
    TokenService,
    extract_bearer_token,
)
from app.database import get_db
from app.models.user import User
from app.repositories.user_repository import (
    SqlAlchemyUserRepository,
    UserRepository,
)
from app.services.admin_user_service import AdminUserService
from app.services.auth_service import AuthService
from app.services.user_profile_service import UserProfileService

_bearer_scheme = HTTPBearer(auto_error=False)
_UNAUTHENTICATED_DETAIL = "Could not validate credentials."


@lru_cache(maxsize=1)
def get_password_policy() -> PasswordPolicy:
    """Return the shared PasswordPolicy instance."""
    return PasswordPolicy()


@lru_cache(maxsize=1)
def get_password_hasher() -> PasswordHasher:
    """Return the lazily configured Argon2id hasher (preserves dummy hash cache)."""
    settings = get_settings()
    return Argon2PasswordHasher(
        time_cost=settings.argon2_time_cost,
        memory_cost=settings.argon2_memory_cost,
        parallelism=settings.argon2_parallelism,
    )


@lru_cache(maxsize=1)
def get_token_service() -> TokenService:
    """Return the lazily configured PyJWT access token service."""
    settings = get_settings()
    return JwtTokenService(
        secret_key=settings.require_jwt_secret_key(),
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        expire_minutes=settings.access_token_expire_minutes,
        leeway_seconds=settings.jwt_leeway_seconds,
    )


@lru_cache(maxsize=1)
def get_login_rate_limiter() -> LoginRateLimiter:
    """Return the process-local in-memory login rate limiter."""
    settings = get_settings()
    return InMemoryLoginRateLimiter(
        account_max_attempts=settings.login_rate_limit_account_max,
        ip_max_attempts=settings.login_rate_limit_ip_max,
        window_seconds=settings.login_rate_limit_window_seconds,
        max_keys=settings.rate_limit_max_keys,
    )


def get_user_repository(
    db: Session = Depends(get_db),
) -> UserRepository:
    """Build a request-scoped SQLAlchemy UserRepository."""
    return SqlAlchemyUserRepository(db)


def get_auth_service(
    user_repository: UserRepository = Depends(get_user_repository),
    password_hasher: PasswordHasher = Depends(get_password_hasher),
    password_policy: PasswordPolicy = Depends(get_password_policy),
    token_service: TokenService = Depends(get_token_service),
    rate_limiter: LoginRateLimiter = Depends(get_login_rate_limiter),
) -> AuthService:
    """Build a request-scoped AuthService with injected dependencies."""
    return AuthService(
        user_repository=user_repository,
        password_hasher=password_hasher,
        password_policy=password_policy,
        token_service=token_service,
        rate_limiter=rate_limiter,
    )


def get_user_profile_service(
    user_repository: UserRepository = Depends(get_user_repository),
) -> UserProfileService:
    """Build a request-scoped UserProfileService."""
    return UserProfileService(user_repository=user_repository)


def get_admin_user_service(
    user_repository: UserRepository = Depends(get_user_repository),
) -> AdminUserService:
    """Build a request-scoped AdminUserService."""
    return AdminUserService(user_repository=user_repository)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_UNAUTHENTICATED_DETAIL,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    request: Request,
    _credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
    token_service: TokenService = Depends(get_token_service),
    user_repository: UserRepository = Depends(get_user_repository),
) -> User:
    """Authenticate Bearer JWT and verify current active status and role from DB.

    Never trusts any role claim inside the JWT; always loads the authoritative
    User record from the repository on every request.
    """
    try:
        raw_token = extract_bearer_token(request.headers.get("authorization"))
        payload = token_service.decode_access_token(raw_token)
    except TokenError as error:
        raise _unauthorized() from error

    user = user_repository.get_by_id(payload.user_id)
    if user is None or not user.is_active:
        raise _unauthorized()

    if parse_user_role(user) is None:
        raise _unauthorized()

    return user


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
]
