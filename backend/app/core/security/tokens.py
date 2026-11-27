"""PyJWT HS256 access token generation and strict claim validation.

Implements Revision 3 §5.1 and §5.3:
- Access-token-only (no refresh tokens, no role claim in token).
- Strict size, structure, algorithm header, signature, required claims,
  temporal bounds, UUID jti, and PostgreSQL INTEGER `sub` validation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import re
from typing import Protocol
from uuid import UUID, uuid4

import jwt
from jwt.exceptions import InvalidTokenError

from app.core.config import MIN_JWT_SECRET_BYTES

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
MAX_TOKEN_BYTES = 4096
MIN_USER_ID = 1
MAX_PG_INT32 = 2_147_483_647
_SUB_PATTERN = re.compile(r"^[1-9][0-9]{0,9}$")
_REQUIRED_CLAIMS = ("sub", "exp", "iat", "nbf", "iss", "aud", "jti", "type")


class TokenError(ValueError):
    """Raised when an access token is missing, malformed, or fails validation."""

    def __init__(self, reason: str) -> None:
        super().__init__("Invalid authentication credentials.")
        self.reason = reason


@dataclass(frozen=True, slots=True)
class AccessTokenPayload:
    """Validated identity metadata extracted from an access token."""

    user_id: int
    jti: str
    issued_at: datetime
    expires_at: datetime


class TokenService(Protocol):
    """Abstraction for access token creation and verification."""

    def create_access_token(self, user_id: int) -> tuple[str, int]: ...

    def decode_access_token(self, token: str) -> AccessTokenPayload: ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_strict_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_user_id(user_id: int) -> int:
    """Ensure a user ID is a valid PostgreSQL positive 32-bit integer."""
    if not _is_strict_int(user_id) or not (MIN_USER_ID <= user_id <= MAX_PG_INT32):
        raise ValueError("Invalid user ID.")
    return user_id


def extract_bearer_token(authorization_header: str | None) -> str:
    """Parse an HTTP Authorization header containing a single Bearer token."""
    if not authorization_header or not isinstance(authorization_header, str):
        raise TokenError("missing_authorization_header")

    parts = authorization_header.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise TokenError("invalid_authorization_header")

    return parts[1]


class JwtTokenService:
    """HS256 PyJWT access token service without role claims."""

    def __init__(
        self,
        *,
        secret_key: str,
        issuer: str = "studygraph-ai",
        audience: str = "studygraph-ai-api",
        expire_minutes: int = 30,
        leeway_seconds: int = 0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not secret_key or len(secret_key.encode("utf-8")) < MIN_JWT_SECRET_BYTES:
            raise ValueError(
                f"JWT_SECRET_KEY must be at least {MIN_JWT_SECRET_BYTES} bytes."
            )
        if not issuer or not issuer.strip():
            raise ValueError("JWT_ISSUER cannot be empty.")
        if not audience or not audience.strip():
            raise ValueError("JWT_AUDIENCE cannot be empty.")
        if not _is_strict_int(expire_minutes) or not (5 <= expire_minutes <= 60):
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must be between 5 and 60.")
        if not _is_strict_int(leeway_seconds) or not (0 <= leeway_seconds <= 30):
            raise ValueError("JWT_LEEWAY_SECONDS must be between 0 and 30.")

        self._secret_key = secret_key
        self._issuer = issuer
        self._audience = audience
        self._expire_minutes = expire_minutes
        self._leeway_seconds = leeway_seconds
        self._clock = clock or _utc_now

    @property
    def expire_seconds(self) -> int:
        return self._expire_minutes * 60

    def create_access_token(self, user_id: int) -> tuple[str, int]:
        """Create a signed HS256 access token and return (token, expires_in)."""
        validated_id = validate_user_id(user_id)
        now = self._clock()
        now_ts = int(now.timestamp())
        exp_ts = now_ts + self.expire_seconds

        payload = {
            "sub": str(validated_id),
            "type": "access",
            "iss": self._issuer,
            "aud": self._audience,
            "iat": now_ts,
            "nbf": now_ts,
            "exp": exp_ts,
            "jti": str(uuid4()),
        }
        encoded = jwt.encode(payload, self._secret_key, algorithm=JWT_ALGORITHM)
        return encoded, self.expire_seconds

    def decode_access_token(self, token: str) -> AccessTokenPayload:
        """Strictly validate a JWT access token and return its parsed payload."""
        if not isinstance(token, str) or not token:
            raise TokenError("empty_token")

        if len(token.encode("utf-8")) > MAX_TOKEN_BYTES:
            raise TokenError("token_too_large")

        segments = token.split(".")
        if len(segments) != 3 or not all(segments):
            raise TokenError("malformed_token_structure")

        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as error:
            logger.debug("JWT header parse failed: %s", type(error).__name__)
            raise TokenError("invalid_header") from error

        if header.get("alg") != JWT_ALGORITHM:
            raise TokenError("invalid_algorithm")

        try:
            claims = jwt.decode(
                token,
                self._secret_key,
                algorithms=[JWT_ALGORITHM],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway_seconds,
                options={
                    "require": list(_REQUIRED_CLAIMS),
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    "verify_iss": True,
                },
            )
        except InvalidTokenError as error:
            logger.debug("JWT decode failed: %s", type(error).__name__)
            raise TokenError(type(error).__name__) from error

        if claims.get("type") != "access":
            raise TokenError("invalid_token_type")

        exp = claims.get("exp")
        iat = claims.get("iat")
        nbf = claims.get("nbf")
        if not (_is_strict_int(exp) and _is_strict_int(iat) and _is_strict_int(nbf)):
            raise TokenError("invalid_timestamp_type")

        now_ts = int(self._clock().timestamp())
        if iat > now_ts + self._leeway_seconds:
            raise TokenError("iat_in_future")
        if nbf > now_ts + self._leeway_seconds:
            raise TokenError("nbf_in_future")
        if exp <= now_ts - self._leeway_seconds:
            raise TokenError("token_expired")
        if exp <= iat or (exp - iat) > self.expire_seconds:
            raise TokenError("invalid_token_lifetime")

        jti = claims.get("jti")
        if not isinstance(jti, str):
            raise TokenError("invalid_jti")
        try:
            parsed_jti = UUID(jti)
        except ValueError as error:
            raise TokenError("invalid_jti") from error
        if str(parsed_jti) != jti.lower():
            raise TokenError("invalid_jti")

        sub = claims.get("sub")
        if not isinstance(sub, str) or not _SUB_PATTERN.fullmatch(sub):
            raise TokenError("invalid_sub")

        user_id = int(sub)
        if not (MIN_USER_ID <= user_id <= MAX_PG_INT32):
            raise TokenError("sub_out_of_range")

        return AccessTokenPayload(
            user_id=user_id,
            jti=jti,
            issued_at=datetime.fromtimestamp(iat, tz=timezone.utc),
            expires_at=datetime.fromtimestamp(exp, tz=timezone.utc),
        )
