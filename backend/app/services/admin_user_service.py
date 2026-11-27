"""Admin user management application service.

Delegates transactional locking and last-active-admin enforcement to
`UserRepository` so business rules remain decoupled from SQLAlchemy sessions.
"""

from __future__ import annotations

from app.authorization.roles import Role
from app.models.user import User
from app.repositories.user_repository import UserNotFoundError, UserRepository


class AdminUserService:
    """Handles admin listing, inspection, role changes, and activation status."""

    def __init__(self, *, user_repository: UserRepository) -> None:
        self._user_repository = user_repository

    def list_users(
        self,
        *,
        role: Role | None = None,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[User], int]:
        """List users with optional role/active filters and pagination."""
        return self._user_repository.list_users(
            role=role,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )

    def get_user(self, user_id: int) -> User:
        """Return a single user by ID or raise UserNotFoundError."""
        user = self._user_repository.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError("User not found.")
        return user

    def change_role(self, user_id: int, new_role: Role) -> User:
        """Change a user's role while protecting the last active admin."""
        return self._user_repository.update_role_with_last_admin_guard(
            user_id,
            new_role,
        )

    def set_active_status(self, user_id: int, is_active: bool) -> User:
        """Activate or deactivate a user while protecting the last active admin."""
        return self._user_repository.update_status_with_last_admin_guard(
            user_id,
            is_active,
        )
