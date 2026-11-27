"""User persistence abstraction and SQLAlchemy 2.0 implementation.

Transaction boundary responsibility:
- `SqlAlchemyUserRepository` owns commit, rollback, and row-level locking
  (`SELECT ... FOR UPDATE`) for persistence mutations (`create`,
  `update_password_hash`, `update_profile_fields`,
  `update_role_with_last_admin_guard`, `update_status_with_last_admin_guard`).
- Read methods (`get_by_id`, `get_by_email`, `list_users`) never commit.
- Application services (`AuthService`, `UserProfileService`, `AdminUserService`)
  never access SQLAlchemy sessions or call commit/rollback directly.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.authorization.roles import Role
from app.models.user import User

EMAIL_UNIQUE_CONSTRAINT_NAME = "uq_users_email"
ALLOWED_PROFILE_UPDATE_FIELDS: frozenset[str] = frozenset(
    {"first_name", "last_name"}
)
LAST_ACTIVE_ADMIN_ERROR_MESSAGE = (
    "LAST_ACTIVE_ADMIN: Cannot deactivate or demote the last active admin."
)


class EmailAlreadyRegisteredError(Exception):
    """Raised when attempting to register an email that already exists."""


class UserNotFoundError(Exception):
    """Raised when a target user record does not exist."""


class InactiveUserError(Exception):
    """Raised when an operation requires an active user but the target is inactive."""


class LastActiveAdminError(Exception):
    """Raised when an operation would leave zero active admin accounts."""


class UserRepository(Protocol):
    """Repository contract for User persistence."""

    def get_by_id(self, user_id: int) -> User | None: ...

    def get_by_email(self, normalized_email: str) -> User | None: ...

    def list_users(
        self,
        *,
        role: Role | None = None,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[User], int]: ...

    def create(
        self,
        *,
        email: str,
        hashed_password: str,
        first_name: str,
        last_name: str,
        role: Role,
        is_active: bool = True,
    ) -> User: ...

    def update_password_hash(
        self,
        user_id: int,
        new_hashed_password: str,
    ) -> None: ...

    def update_profile_fields(
        self,
        user_id: int,
        updates: Mapping[str, str],
    ) -> User: ...

    def update_role_with_last_admin_guard(
        self,
        user_id: int,
        new_role: Role,
        *,
        require_active: bool = False,
    ) -> User: ...

    def update_status_with_last_admin_guard(
        self,
        user_id: int,
        is_active: bool,
    ) -> User: ...


def _is_email_unique_violation(error: IntegrityError) -> bool:
    orig = getattr(error, "orig", None)
    diag = getattr(orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None)
    if constraint_name == EMAIL_UNIQUE_CONSTRAINT_NAME:
        return True
    return EMAIL_UNIQUE_CONSTRAINT_NAME in str(orig)


class SqlAlchemyUserRepository:
    """SQLAlchemy 2.0 implementation of UserRepository."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, user_id: int) -> User | None:
        return self._session.get(User, user_id)

    def get_by_email(self, normalized_email: str) -> User | None:
        statement = select(User).where(User.email == normalized_email)
        return self._session.execute(statement).scalar_one_or_none()

    def list_users(
        self,
        *,
        role: Role | None = None,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[User], int]:
        filters = []
        if role is not None:
            filters.append(User.role == role.value)
        if is_active is not None:
            filters.append(User.is_active.is_(is_active))

        count_stmt = select(func.count(User.id)).where(*filters)
        total = int(self._session.execute(count_stmt).scalar_one())

        items_stmt = (
            select(User)
            .where(*filters)
            .order_by(User.id.asc())
            .limit(limit)
            .offset(offset)
        )
        items = list(self._session.execute(items_stmt).scalars().all())
        return items, total

    def create(
        self,
        *,
        email: str,
        hashed_password: str,
        first_name: str,
        last_name: str,
        role: Role,
        is_active: bool = True,
    ) -> User:
        user = User(
            email=email,
            hashed_password=hashed_password,
            first_name=first_name,
            last_name=last_name,
            role=role.value,
            is_active=is_active,
        )
        self._session.add(user)
        try:
            self._session.commit()
        except IntegrityError as error:
            self._session.rollback()
            if _is_email_unique_violation(error):
                raise EmailAlreadyRegisteredError(
                    "An account with this email already exists."
                ) from error
            raise
        except Exception:
            self._session.rollback()
            raise

        self._session.refresh(user)
        return user

    def update_password_hash(
        self,
        user_id: int,
        new_hashed_password: str,
    ) -> None:
        user = self._session.get(User, user_id)
        if user is None:
            return
        user.hashed_password = new_hashed_password
        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

    def update_profile_fields(
        self,
        user_id: int,
        updates: Mapping[str, str],
    ) -> User:
        disallowed = set(updates.keys()) - ALLOWED_PROFILE_UPDATE_FIELDS
        if disallowed:
            raise ValueError("Disallowed profile update field.")

        user = self._session.get(User, user_id)
        if user is None:
            raise UserNotFoundError("User not found.")

        for field_name, value in updates.items():
            setattr(user, field_name, value)

        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

        self._session.refresh(user)
        return user

    def _lock_active_admin_ids(self) -> list[int]:
        """Lock all active admin rows in deterministic ID order to avoid deadlocks."""
        stmt = (
            select(User.id)
            .where(User.role == Role.ADMIN.value, User.is_active.is_(True))
            .order_by(User.id.asc())
            .with_for_update()
        )
        return list(self._session.execute(stmt).scalars().all())

    def _get_target_for_update(self, user_id: int) -> User | None:
        stmt = (
            select(User)
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def _mutate_with_last_admin_guard(
        self,
        user_id: int,
        *,
        lock_active_admins: bool,
        require_active: bool,
        removes_active_admin: Callable[[User], bool],
        apply_mutation: Callable[[User], None],
    ) -> User:
        """Execute a locked user mutation enforcing active/last-admin invariants."""
        try:
            locked_admin_ids: list[int] | None = None
            if lock_active_admins:
                locked_admin_ids = self._lock_active_admin_ids()

            target = self._get_target_for_update(user_id)
            if target is None:
                self._session.rollback()
                raise UserNotFoundError("User not found.")

            if require_active and not target.is_active:
                self._session.rollback()
                raise InactiveUserError("Cannot promote an inactive user account.")

            if removes_active_admin(target):
                if locked_admin_ids is None:
                    self._session.rollback()
                    raise RuntimeError("Active admin rows were not locked before mutation.")
                remaining = [aid for aid in locked_admin_ids if aid != target.id]
                if not remaining:
                    self._session.rollback()
                    raise LastActiveAdminError(LAST_ACTIVE_ADMIN_ERROR_MESSAGE)

            apply_mutation(target)
            self._session.commit()
            self._session.refresh(target)
            return target
        except (UserNotFoundError, InactiveUserError, LastActiveAdminError):
            raise
        except Exception:
            self._session.rollback()
            raise

    def update_role_with_last_admin_guard(
        self,
        user_id: int,
        new_role: Role,
        *,
        require_active: bool = False,
    ) -> User:
        def _apply(target: User) -> None:
            target.role = new_role.value

        return self._mutate_with_last_admin_guard(
            user_id,
            lock_active_admins=new_role != Role.ADMIN,
            require_active=require_active,
            removes_active_admin=lambda target: (
                target.role == Role.ADMIN.value
                and target.is_active is True
                and new_role != Role.ADMIN
            ),
            apply_mutation=_apply,
        )

    def update_status_with_last_admin_guard(
        self,
        user_id: int,
        is_active: bool,
    ) -> User:
        def _apply(target: User) -> None:
            target.is_active = is_active

        return self._mutate_with_last_admin_guard(
            user_id,
            lock_active_admins=not is_active,
            require_active=False,
            removes_active_admin=lambda target: (
                target.role == Role.ADMIN.value
                and target.is_active is True
                and not is_active
            ),
            apply_mutation=_apply,
        )
