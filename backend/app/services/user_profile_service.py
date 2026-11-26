"""Self-service user profile application service.

Applies a second-layer allowlist (`first_name`, `last_name`) independently of
schema validation so privileged fields (`role`, `is_active`, `email`, `id`)
can never be mutated through profile updates.
"""

from __future__ import annotations

from app.models.user import User
from app.repositories.user_repository import (
    ALLOWED_PROFILE_UPDATE_FIELDS,
    UserRepository,
)


class UserProfileService:
    """Handles reading and updating the authenticated user's own profile."""

    def __init__(self, *, user_repository: UserRepository) -> None:
        self._user_repository = user_repository

    def get_profile(self, current_user: User) -> User:
        """Return the authenticated user's profile."""
        return current_user

    def update_profile(
        self,
        current_user: User,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> User:
        """Update only allowlisted profile fields for the authenticated user."""
        candidate_updates: dict[str, str] = {}
        if first_name is not None:
            candidate_updates["first_name"] = first_name
        if last_name is not None:
            candidate_updates["last_name"] = last_name

        safe_updates = {
            key: value
            for key, value in candidate_updates.items()
            if key in ALLOWED_PROFILE_UPDATE_FIELDS
        }
        if not safe_updates:
            raise ValueError("At least one profile field must be provided.")

        return self._user_repository.update_profile_fields(
            current_user.id,
            safe_updates,
        )
