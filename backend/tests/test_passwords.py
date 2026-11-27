"""Unit tests for PasswordPolicy, Argon2PasswordHasher, and lazy dummy hash."""

from __future__ import annotations

import pytest

from app.core.security.passwords import (
    Argon2PasswordHasher,
    PasswordPolicy,
    PasswordPolicyError,
)


def _fast_valid_hasher() -> Argon2PasswordHasher:
    """Return a real Argon2id hasher using the minimum allowed security floor."""
    return Argon2PasswordHasher(
        time_cost=2,
        memory_cost=19456,
        parallelism=1,
    )


def test_password_policy_length_boundaries() -> None:
    policy = PasswordPolicy()

    with pytest.raises(PasswordPolicyError):
        policy.validate("a" * 14)

    policy.validate("a" * 15)
    policy.validate("a" * 128)

    with pytest.raises(PasswordPolicyError):
        policy.validate("a" * 129)


def test_password_policy_utf8_byte_limit_enforced_without_bcrypt_72_limit() -> None:
    policy = PasswordPolicy()
    # 90 ASCII bytes (>72) must be accepted cleanly (no bcrypt 72-byte cap).
    policy.validate("x" * 90)

    # Custom policy to prove UTF-8 byte cap is checked independently of char count.
    tight_byte_policy = PasswordPolicy(
        min_length=15,
        max_length=128,
        max_utf8_bytes=40,
    )
    # 15 Turkish 2-byte characters = 30 UTF-8 bytes -> OK
    tight_byte_policy.validate("ş" * 15)
    # 21 Turkish 2-byte characters = 42 UTF-8 bytes (> 40) -> rejected
    with pytest.raises(PasswordPolicyError):
        tight_byte_policy.validate("ş" * 21)


def test_password_policy_does_not_trim_whitespace_and_rejects_email_match() -> None:
    policy = PasswordPolicy()
    # 15 spaces is 15 characters and not trimmed by policy.
    policy.validate(" " * 15)

    with pytest.raises(PasswordPolicyError):
        policy.validate("Student@Example.Edu", email="student@example.edu")


def test_argon2_hash_verify_salt_and_no_72_byte_truncation() -> None:
    hasher = _fast_valid_hasher()
    pw_base = "A" * 80 + "1"
    pw_diff_tail = "A" * 80 + "2"

    h1 = hasher.hash(pw_base)
    h2 = hasher.hash(pw_base)

    assert h1.startswith("$argon2id$")
    assert h1 != h2  # unique random salt per hash
    assert hasher.verify(pw_base, h1) is True
    assert hasher.verify(pw_diff_tail, h1) is False
    assert hasher.verify("wrong-password-15+", h1) is False


def test_argon2_verify_does_not_trim_whitespace() -> None:
    hasher = _fast_valid_hasher()
    raw = "  padded-password-15  "
    hashed = hasher.hash(raw)

    assert hasher.verify(raw, hashed) is True
    assert hasher.verify(raw.strip(), hashed) is False


def test_argon2_corrupted_or_empty_hash_returns_false() -> None:
    hasher = _fast_valid_hasher()
    assert hasher.verify("valid-password-15+", "") is False
    assert hasher.verify("valid-password-15+", "not-a-valid-phc-hash") is False
    assert hasher.needs_rehash("not-a-valid-phc-hash") is False


def test_argon2_needs_rehash_detects_parameter_upgrade() -> None:
    old_hasher = Argon2PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
    new_hasher = Argon2PasswordHasher(time_cost=3, memory_cost=19456, parallelism=1)

    old_hash = old_hasher.hash("rehash-test-password-15")
    assert old_hasher.needs_rehash(old_hash) is False
    assert new_hasher.needs_rehash(old_hash) is True
    assert new_hasher.verify("rehash-test-password-15", old_hash) is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"time_cost": 1},
        {"memory_cost": 19455},
        {"parallelism": 0},
        {"hash_len": 15},
        {"salt_len": 15},
    ],
)
def test_argon2_enforces_minimum_security_parameters(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        Argon2PasswordHasher(**kwargs)


def test_lazy_random_dummy_hash_generated_once_and_always_returns_false() -> None:
    hasher = _fast_valid_hasher()
    assert hasher._dummy_hash is None

    first = hasher.get_dummy_hash()
    second = hasher.get_dummy_hash()

    assert first.startswith("$argon2id$")
    assert first == second
    assert hasher.verify_dummy("any-candidate-password-15") is False

    # Independent instances generate distinct random dummy hashes (no hardcoded constant).
    other = _fast_valid_hasher()
    assert other.get_dummy_hash() != first
