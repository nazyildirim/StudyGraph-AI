"""Reusable test doubles for database-free unit and API tests.

These fakes are strictly for unit/API testing and are NOT a substitute for
real PostgreSQL integration tests (tests/integration/).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import threading

from app.authorization.roles import Role
from app.models.user import User
from app.repositories.user_repository import (
    ALLOWED_PROFILE_UPDATE_FIELDS,
    LAST_ACTIVE_ADMIN_ERROR_MESSAGE,
    EmailAlreadyRegisteredError,
    InactiveUserError,
    LastActiveAdminError,
    UserNotFoundError,
)


class FakeClock:
    """Deterministic UTC and monotonic clock for tests."""

    def __init__(self, initial: datetime | None = None) -> None:
        self.current = initial or datetime.now(timezone.utc)
        self.monotonic_now = 1000.0

    def utc_now(self) -> datetime:
        return self.current

    def monotonic(self) -> float:
        return self.monotonic_now

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)
        self.monotonic_now += seconds


class FakePasswordHasher:
    """Fast deterministic PasswordHasher double that tracks calls."""

    def __init__(self, *, rehash_prefix: str = "old$") -> None:
        self._rehash_prefix = rehash_prefix
        self.hash_calls = 0
        self.verify_calls = 0
        self.verify_dummy_calls = 0
        self.last_dummy_input: str | None = None

    def hash(self, password: str) -> str:
        self.hash_calls += 1
        return f"fakehash${password}"

    def verify(self, password: str, hashed_password: str) -> bool:
        self.verify_calls += 1
        if hashed_password.startswith("fakehash$"):
            return hashed_password == f"fakehash${password}"
        if hashed_password.startswith(self._rehash_prefix):
            return hashed_password == f"{self._rehash_prefix}{password}"
        return False

    def needs_rehash(self, hashed_password: str) -> bool:
        return hashed_password.startswith(self._rehash_prefix)

    def verify_dummy(self, password: str) -> bool:
        self.verify_dummy_calls += 1
        self.last_dummy_input = password
        return False


class FakeUserRepository:
    """Thread-safe in-memory UserRepository double for unit and API tests."""

    def __init__(self, *, simulate_create_race: bool = False) -> None:
        self._lock = threading.Lock()
        self._users_by_id: dict[int, User] = {}
        self._users_by_email: dict[str, User] = {}
        self._next_id = 1
        self._simulate_create_race = simulate_create_race
        self.password_updates: list[tuple[int, str]] = []

    def get_by_id(self, user_id: int) -> User | None:
        with self._lock:
            return self._users_by_id.get(user_id)

    def get_by_email(self, normalized_email: str) -> User | None:
        with self._lock:
            return self._users_by_email.get(normalized_email)

    def list_users(
        self,
        *,
        role: Role | None = None,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[User], int]:
        with self._lock:
            users = sorted(self._users_by_id.values(), key=lambda u: u.id)
            if role is not None:
                users = [u for u in users if u.role == role.value]
            if is_active is not None:
                users = [u for u in users if u.is_active is is_active]
            total = len(users)
            return users[offset : offset + limit], total

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
        with self._lock:
            if self._simulate_create_race or email in self._users_by_email:
                raise EmailAlreadyRegisteredError(
                    "An account with this email already exists."
                )

            now = datetime.now(timezone.utc)
            user = User(
                id=self._next_id,
                email=email,
                hashed_password=hashed_password,
                first_name=first_name,
                last_name=last_name,
                role=role.value,
                is_active=is_active,
                created_at=now,
                updated_at=now,
            )
            self._next_id += 1
            self._users_by_id[user.id] = user
            self._users_by_email[user.email] = user
            return user

    def update_password_hash(
        self,
        user_id: int,
        new_hashed_password: str,
    ) -> None:
        with self._lock:
            user = self._users_by_id.get(user_id)
            if user is None:
                return
            user.hashed_password = new_hashed_password
            user.updated_at = datetime.now(timezone.utc)
            self.password_updates.append((user_id, new_hashed_password))

    def update_profile_fields(
        self,
        user_id: int,
        updates: Mapping[str, str],
    ) -> User:
        disallowed = set(updates.keys()) - ALLOWED_PROFILE_UPDATE_FIELDS
        if disallowed:
            raise ValueError("Disallowed profile update field.")
        with self._lock:
            user = self._users_by_id.get(user_id)
            if user is None:
                raise UserNotFoundError("User not found.")
            for key, value in updates.items():
                setattr(user, key, value)
            user.updated_at = datetime.now(timezone.utc)
            return user

    def _active_admin_ids_unlocked(self) -> list[int]:
        return [
            u.id
            for u in self._users_by_id.values()
            if u.role == Role.ADMIN.value and u.is_active is True
        ]

    def update_role_with_last_admin_guard(
        self,
        user_id: int,
        new_role: Role,
        *,
        require_active: bool = False,
    ) -> User:
        with self._lock:
            target = self._users_by_id.get(user_id)
            if target is None:
                raise UserNotFoundError("User not found.")

            if require_active and not target.is_active:
                raise InactiveUserError("Cannot promote an inactive user account.")

            is_removing_active_admin = (
                target.role == Role.ADMIN.value
                and target.is_active is True
                and new_role != Role.ADMIN
            )
            if is_removing_active_admin:
                remaining = [
                    aid for aid in self._active_admin_ids_unlocked() if aid != target.id
                ]
                if not remaining:
                    raise LastActiveAdminError(LAST_ACTIVE_ADMIN_ERROR_MESSAGE)

            target.role = new_role.value
            target.updated_at = datetime.now(timezone.utc)
            return target

    def update_status_with_last_admin_guard(
        self,
        user_id: int,
        is_active: bool,
    ) -> User:
        with self._lock:
            target = self._users_by_id.get(user_id)
            if target is None:
                raise UserNotFoundError("User not found.")

            is_deactivating_active_admin = (
                target.role == Role.ADMIN.value
                and target.is_active is True
                and not is_active
            )
            if is_deactivating_active_admin:
                remaining = [
                    aid for aid in self._active_admin_ids_unlocked() if aid != target.id
                ]
                if not remaining:
                    raise LastActiveAdminError(LAST_ACTIVE_ADMIN_ERROR_MESSAGE)

            target.is_active = is_active
            target.updated_at = datetime.now(timezone.utc)
            return target

    def delete(self, user_id: int) -> None:
        with self._lock:
            user = self._users_by_id.pop(user_id, None)
            if user is not None:
                self._users_by_email.pop(user.email, None)


class FakeOwnerResolver:
    """In-memory ResourceOwnerResolver double for ownership policy tests."""

    def __init__(self, owners: dict[int, int] | None = None) -> None:
        self._owners: dict[int, int] = dict(owners or {})
        self.lookup_calls: list[int] = []

    def get_owner_id(self, resource_id: int) -> int | None:
        self.lookup_calls.append(resource_id)
        return self._owners.get(resource_id)
