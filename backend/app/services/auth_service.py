"""Authentication application service (registration and login orchestration).

Transaction boundary:
- `AuthService` coordinates domain validation, rate limiting, password hashing,
  and JWT issuance through Protocol abstractions.
- Persistence commit/rollback is delegated strictly to `UserRepository`.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.authorization.roles import Role
from app.core.security.email import normalize_email
from app.core.security.passwords import (
    MAX_PASSWORD_LENGTH,
    MAX_PASSWORD_UTF8_BYTES,
    PasswordHasher,
    PasswordPolicy,
)
from app.core.security.rate_limit import LoginRateLimiter
from app.core.security.tokens import TokenService
from app.models.user import User
from app.repositories.user_repository import (
    EmailAlreadyRegisteredError,
    UserRepository,
)

GENERIC_AUTH_ERROR_MESSAGE = "Invalid email or password."
_OVERSIZED_PASSWORD_DUMMY_INPUT = "invalid-password-placeholder"


class InvalidCredentialsError(Exception):
    """Raised on any failed login (unknown email, wrong password, or inactive user)."""


@dataclass(frozen=True, slots=True)
class AuthTokenResult:
    """Result returned upon successful authentication."""

    access_token: str
    expires_in: int
    token_type: str = "bearer"


def _is_login_password_within_safe_bounds(password: str) -> bool:
    if not isinstance(password, str) or not password:
        return False
    if len(password) > MAX_PASSWORD_LENGTH:
        return False
    return len(password.encode("utf-8")) <= MAX_PASSWORD_UTF8_BYTES


class AuthService:
    """Handles student registration and access-token login."""

    def __init__(
        self,
        *,
        user_repository: UserRepository,
        password_hasher: PasswordHasher,
        password_policy: PasswordPolicy,
        token_service: TokenService,
        rate_limiter: LoginRateLimiter,
    ) -> None:
        self._user_repository = user_repository
        self._password_hasher = password_hasher
        self._password_policy = password_policy
        self._token_service = token_service
        self._rate_limiter = rate_limiter

    def register(
        self,
        *,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
    ) -> User:
        """Register a new active student account."""
        normalized_email = normalize_email(email)
        self._password_policy.validate(password, email=normalized_email)

        existing = self._user_repository.get_by_email(normalized_email)
        if existing is not None:
            raise EmailAlreadyRegisteredError(
                "An account with this email already exists."
            )

        hashed_password = self._password_hasher.hash(password)
        return self._user_repository.create(
            email=normalized_email,
            hashed_password=hashed_password,
            first_name=first_name,
            last_name=last_name,
            role=Role.STUDENT,
            is_active=True,
        )

    def login(
        self,
        *,
        email: str,
        password: str,
        client_ip: str,
    ) -> AuthTokenResult:
        """Authenticate an active user and issue an HS256 access token."""
        normalized_email = normalize_email(email)

        with self._rate_limiter.acquire(
            client_ip=client_ip,
            normalized_email=normalized_email,
        ) as reservation:
            if not _is_login_password_within_safe_bounds(password):
                self._password_hasher.verify_dummy(_OVERSIZED_PASSWORD_DUMMY_INPUT)
                reservation.record_failure()
                raise InvalidCredentialsError(GENERIC_AUTH_ERROR_MESSAGE)

            user = self._user_repository.get_by_email(normalized_email)
            if user is None or not user.is_active:
                self._password_hasher.verify_dummy(password)
                reservation.record_failure()
                raise InvalidCredentialsError(GENERIC_AUTH_ERROR_MESSAGE)

            if not self._password_hasher.verify(password, user.hashed_password):
                reservation.record_failure()
                raise InvalidCredentialsError(GENERIC_AUTH_ERROR_MESSAGE)

            if self._password_hasher.needs_rehash(user.hashed_password):
                rehashed = self._password_hasher.hash(password)
                self._user_repository.update_password_hash(user.id, rehashed)

            reservation.record_success()

        access_token, expires_in = self._token_service.create_access_token(user.id)
        return AuthTokenResult(
            access_token=access_token,
            expires_in=expires_in,
        )
