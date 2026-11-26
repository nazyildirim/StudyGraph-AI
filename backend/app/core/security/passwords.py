"""Argon2id password hashing, PasswordPolicy, and lazy random dummy hash.

Implements Revision 3 §6.1 and §6.5:
- Argon2id via argon2-cffi (no bcrypt, no 72-byte truncation limit).
- PasswordPolicy: 15-128 Unicode characters, max 512 UTF-8 bytes (DoS guard),
  no whitespace trimming, no composition rules, rejects password == email.
- Lazy, thread-safe, randomly generated dummy hash for timing mitigation.
"""

from __future__ import annotations

import logging
import secrets
import threading
from typing import Protocol

from argon2 import PasswordHasher as Argon2LibHasher
from argon2 import Type
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

logger = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 15
MAX_PASSWORD_LENGTH = 128
MAX_PASSWORD_UTF8_BYTES = 512

MIN_ARGON2_TIME_COST = 2
MIN_ARGON2_MEMORY_COST = 19456  # 19 MiB (OWASP minimum floor)
MIN_ARGON2_PARALLELISM = 1
MIN_ARGON2_HASH_LEN = 16
MIN_ARGON2_SALT_LEN = 16


class PasswordPolicyError(ValueError):
    """Raised when a candidate password violates PasswordPolicy."""


class PasswordPolicy:
    """Single source of truth for password validation (API and CLI)."""

    def __init__(
        self,
        *,
        min_length: int = MIN_PASSWORD_LENGTH,
        max_length: int = MAX_PASSWORD_LENGTH,
        max_utf8_bytes: int = MAX_PASSWORD_UTF8_BYTES,
    ) -> None:
        if min_length < 1 or max_length < min_length:
            raise ValueError("Invalid password length bounds.")
        if max_utf8_bytes < min_length:
            raise ValueError("Invalid UTF-8 byte upper bound.")
        self._min_length = min_length
        self._max_length = max_length
        self._max_utf8_bytes = max_utf8_bytes

    def validate(self, password: str, *, email: str | None = None) -> None:
        """Validate a raw password without trimming whitespace."""
        if not isinstance(password, str):
            raise PasswordPolicyError("Password must be a string.")

        char_len = len(password)
        if char_len < self._min_length:
            raise PasswordPolicyError(
                f"Password must be at least {self._min_length} characters."
            )
        if char_len > self._max_length:
            raise PasswordPolicyError(
                f"Password must be at most {self._max_length} characters."
            )

        utf8_len = len(password.encode("utf-8"))
        if utf8_len > self._max_utf8_bytes:
            raise PasswordPolicyError(
                f"Password must be at most {self._max_utf8_bytes} bytes."
            )

        if email is not None and password.strip().lower() == email.strip().lower():
            raise PasswordPolicyError(
                "Password cannot be the same as the email address."
            )


class PasswordHasher(Protocol):
    """Abstraction for password hashing and verification."""

    def hash(self, password: str) -> str: ...

    def verify(self, password: str, hashed_password: str) -> bool: ...

    def needs_rehash(self, hashed_password: str) -> bool: ...

    def verify_dummy(self, password: str) -> bool: ...


class Argon2PasswordHasher:
    """Argon2id implementation backed by argon2-cffi."""

    def __init__(
        self,
        *,
        time_cost: int = 3,
        memory_cost: int = 65536,
        parallelism: int = 4,
        hash_len: int = 32,
        salt_len: int = 16,
    ) -> None:
        if time_cost < MIN_ARGON2_TIME_COST:
            raise ValueError(
                f"Argon2 time_cost must be at least {MIN_ARGON2_TIME_COST}."
            )
        if memory_cost < MIN_ARGON2_MEMORY_COST:
            raise ValueError(
                f"Argon2 memory_cost must be at least {MIN_ARGON2_MEMORY_COST} KiB."
            )
        if parallelism < MIN_ARGON2_PARALLELISM:
            raise ValueError(
                f"Argon2 parallelism must be at least {MIN_ARGON2_PARALLELISM}."
            )
        if hash_len < MIN_ARGON2_HASH_LEN:
            raise ValueError(
                f"Argon2 hash_len must be at least {MIN_ARGON2_HASH_LEN}."
            )
        if salt_len < MIN_ARGON2_SALT_LEN:
            raise ValueError(
                f"Argon2 salt_len must be at least {MIN_ARGON2_SALT_LEN}."
            )

        self._hasher = Argon2LibHasher(
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            hash_len=hash_len,
            salt_len=salt_len,
            type=Type.ID,
        )
        self._dummy_lock = threading.Lock()
        self._dummy_hash: str | None = None

    def hash(self, password: str) -> str:
        """Hash a password using Argon2id."""
        return self._hasher.hash(password)

    def verify(self, password: str, hashed_password: str) -> bool:
        """Verify a password against an Argon2id PHC hash string."""
        if not isinstance(hashed_password, str) or not hashed_password:
            return False
        try:
            return bool(self._hasher.verify(hashed_password, password))
        except VerifyMismatchError:
            return False
        except (InvalidHashError, VerificationError) as error:
            logger.warning(
                "Password verification failed due to invalid hash format: %s",
                type(error).__name__,
            )
            return False

    def needs_rehash(self, hashed_password: str) -> bool:
        """Return True if the stored hash uses outdated Argon2 parameters."""
        try:
            return bool(self._hasher.check_needs_rehash(hashed_password))
        except InvalidHashError:
            return False

    def get_dummy_hash(self) -> str:
        """Lazily generate and cache a random Argon2id hash for timing parity."""
        if self._dummy_hash is None:
            with self._dummy_lock:
                if self._dummy_hash is None:
                    self._dummy_hash = self._hasher.hash(
                        secrets.token_urlsafe(32)
                    )
        return self._dummy_hash

    def verify_dummy(self, password: str) -> bool:
        """Run a full Argon2id verification against the dummy hash and return False."""
        self.verify(password, self.get_dummy_hash())
        return False
