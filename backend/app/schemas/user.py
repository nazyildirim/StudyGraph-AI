"""User, profile update, and admin user management schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, StrictBool, field_validator, model_validator

from app.authorization.roles import Role

MAX_NAME_LENGTH = 100


class _StrictUserRequestBase(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class UserResponse(BaseModel):
    """Public representation of a user account (never exposes password hashes)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    first_name: str
    last_name: str
    role: Role
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProfileUpdateRequest(_StrictUserRequestBase):
    """Allowlisted payload for self-service profile updates (`PATCH /users/me`)."""

    first_name: str | None = None
    last_name: str | None = None

    @field_validator("first_name", "last_name")
    @classmethod
    def _validate_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Name cannot be blank.")
        if len(stripped) > MAX_NAME_LENGTH:
            raise ValueError(
                f"Name must be at most {MAX_NAME_LENGTH} characters."
            )
        return stripped

    @model_validator(mode="after")
    def _require_at_least_one_field(self) -> ProfileUpdateRequest:
        if self.first_name is None and self.last_name is None:
            raise ValueError("At least one profile field must be provided.")
        return self


class AdminRoleUpdateRequest(_StrictUserRequestBase):
    """Payload for changing a user's role (`PATCH /admin/users/{user_id}/role`)."""

    role: Role


class AdminStatusUpdateRequest(_StrictUserRequestBase):
    """Payload for changing a user's active status (`PATCH /admin/users/{user_id}/status`)."""

    is_active: StrictBool


class AdminUserListResponse(BaseModel):
    """Paginated list of users for admin management."""

    items: list[UserResponse]
    total: int
    limit: int
    offset: int
