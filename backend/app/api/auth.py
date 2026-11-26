"""Authentication HTTP router (`/auth/register` and `/auth/login`).

Security notes:
- `POST /auth/register` returns `409 Conflict` when an email is already
  registered. This is a documented UX/security trade-off that permits account
  enumeration on registration (to be tracked in docs/SECURITY_RISKS.md).
- `POST /auth/login` uses `request.client.host` directly and ignores untrusted
  `X-Forwarded-For` headers.
- Passwords, hashes, and tokens are never logged; access tokens are returned
  only in a successful `POST /auth/login` response.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.dependencies.auth import get_auth_service
from app.api.routing import SanitizedValidationRoute
from app.core.security.email import InvalidEmailError
from app.core.security.passwords import PasswordPolicyError
from app.core.security.rate_limit import RateLimitExceededError
from app.repositories.user_repository import EmailAlreadyRegisteredError
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.schemas.user import UserResponse
from app.services.auth_service import AuthService, InvalidCredentialsError

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
    route_class=SanitizedValidationRoute,
)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_user(
    payload: RegisterRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> UserResponse:
    """Register a new student account."""
    try:
        user = auth_service.register(
            email=payload.email,
            password=payload.password.get_secret_value(),
            first_name=payload.first_name,
            last_name=payload.last_name,
        )
    except (InvalidEmailError, PasswordPolicyError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except EmailAlreadyRegisteredError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error

    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
)
def login_user(
    payload: LoginRequest,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Authenticate an active user and issue an access token."""
    client_ip = request.client.host if request.client is not None else "unknown"
    try:
        result = auth_service.login(
            email=payload.email,
            password=payload.password.get_secret_value(),
            client_ip=client_ip,
        )
    except InvalidEmailError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except RateLimitExceededError as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(error),
            headers={"Retry-After": str(error.retry_after)},
        ) from error
    except InvalidCredentialsError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(error),
            headers={"WWW-Authenticate": "Bearer"},
        ) from error

    return TokenResponse(
        access_token=result.access_token,
        token_type="bearer",
        expires_in=result.expires_in,
    )
