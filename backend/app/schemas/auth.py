"""Authentication request and response schemas.

Security rules:
- `extra="forbid"` rejects privilege-escalation fields (e.g., `role`, `is_active`).
- `str_strip_whitespace` is intentionally NOT enabled so passwords are never
  silently trimmed.
- Password fields use `SecretStr` to prevent accidental exposure in repr/logs.
- No cross-field `model_validator` is used so Pydantic never echoes the raw
  request dict (including password) in validation error payloads.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, SecretStr, field_validator

MAX_NAME_LENGTH = 100


class _AuthRequestBase(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class RegisterRequest(_AuthRequestBase):
    """Payload for student self-registration."""

    email: str
    password: SecretStr
    first_name: str
    last_name: str

    @field_validator("first_name", "last_name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Name cannot be blank.")
        if len(stripped) > MAX_NAME_LENGTH:
            raise ValueError(
                f"Name must be at most {MAX_NAME_LENGTH} characters."
            )
        return stripped


class LoginRequest(_AuthRequestBase):
    """Payload for email/password login."""

    email: str
    password: SecretStr


class TokenResponse(BaseModel):
    """Access-token-only login response (no refresh token in Phase 1)."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
