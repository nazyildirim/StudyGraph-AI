"""Unit tests for email normalization, SqlAlchemyUserRepository, and AuthService."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.authorization.roles import Role
from app.core.security.email import InvalidEmailError, normalize_email
from app.core.security.passwords import PasswordPolicy, PasswordPolicyError
from app.core.security.rate_limit import (
    InMemoryLoginRateLimiter,
    RateLimitExceededError,
)
from app.core.security.tokens import JwtTokenService
from app.repositories.user_repository import (
    EmailAlreadyRegisteredError,
    SqlAlchemyUserRepository,
)
from app.services.auth_service import AuthService, InvalidCredentialsError
from tests.fakes import FakeClock, FakePasswordHasher, FakeUserRepository

TEST_JWT_SECRET = "T" * 48


def _make_auth_service(
    *,
    repo: FakeUserRepository | None = None,
    hasher: FakePasswordHasher | None = None,
    clock: FakeClock | None = None,
    account_max_attempts: int = 5,
) -> tuple[AuthService, FakeUserRepository, FakePasswordHasher, FakeClock, JwtTokenService]:
    active_clock = clock or FakeClock()
    active_repo = repo or FakeUserRepository()
    active_hasher = hasher or FakePasswordHasher()
    token_service = JwtTokenService(
        secret_key=TEST_JWT_SECRET,
        clock=active_clock.utc_now,
    )
    rate_limiter = InMemoryLoginRateLimiter(
        account_max_attempts=account_max_attempts,
        ip_max_attempts=30,
        window_seconds=900,
        clock=active_clock.monotonic,
    )
    service = AuthService(
        user_repository=active_repo,
        password_hasher=active_hasher,
        password_policy=PasswordPolicy(),
        token_service=token_service,
        rate_limiter=rate_limiter,
    )
    return service, active_repo, active_hasher, active_clock, token_service


def test_normalize_email_lowercases_trims_and_preserves_provider_chars() -> None:
    assert normalize_email("  Student.Name+Tag@Example.EDU  ") == (
        "student.name+tag@example.edu"
    )
    assert normalize_email("a.b+plus@gmail.com") == "a.b+plus@gmail.com"


@pytest.mark.parametrize(
    "bad_email",
    [
        "",
        "   ",
        "not-an-email",
        "missing-domain@",
        "@missing-local.edu",
        f"{'a' * 64}@{'b' * 63}.{'c' * 63}.{'d' * 60}.edu",
    ],
)
def test_normalize_email_rejects_invalid_and_oversized(bad_email: str) -> None:
    with pytest.raises(InvalidEmailError):
        normalize_email(bad_email)


def test_sqlalchemy_repo_translates_email_unique_violation_and_rolls_back() -> None:
    session = MagicMock()
    orig = SimpleNamespace(diag=SimpleNamespace(constraint_name="uq_users_email"))
    session.commit.side_effect = IntegrityError("INSERT", {}, orig)

    repo = SqlAlchemyUserRepository(session)
    with pytest.raises(EmailAlreadyRegisteredError):
        repo.create(
            email="dup@example.edu",
            hashed_password="hash",
            first_name="Ada",
            last_name="Lovelace",
            role=Role.STUDENT,
        )

    session.rollback.assert_called_once()


def test_sqlalchemy_repo_reraises_unrelated_integrity_error_after_rollback() -> None:
    session = MagicMock()
    orig = SimpleNamespace(diag=SimpleNamespace(constraint_name="ck_users_role"))
    session.commit.side_effect = IntegrityError("INSERT", {}, orig)

    repo = SqlAlchemyUserRepository(session)
    with pytest.raises(IntegrityError):
        repo.create(
            email="user@example.edu",
            hashed_password="hash",
            first_name="Ada",
            last_name="Lovelace",
            role=Role.STUDENT,
        )

    session.rollback.assert_called_once()


def test_register_creates_active_student_with_normalized_email() -> None:
    service, repo, hasher, _clock, _tokens = _make_auth_service()

    user = service.register(
        email="  Student@Example.EDU ",
        password="  valid-password-15  ",
        first_name="Ada",
        last_name="Lovelace",
    )

    assert user.email == "student@example.edu"
    assert user.role == Role.STUDENT.value
    assert user.is_active is True
    assert user.hashed_password == "fakehash$  valid-password-15  "
    assert hasher.hash_calls == 1
    assert repo.get_by_email("student@example.edu") is user


def test_register_handles_concurrent_duplicate_from_repository() -> None:
    repo = FakeUserRepository(simulate_create_race=True)
    service, _repo, _hasher, _clock, _tokens = _make_auth_service(repo=repo)

    with pytest.raises(EmailAlreadyRegisteredError):
        service.register(
            email="race@example.edu",
            password="valid-password-15-chars",
            first_name="Ada",
            last_name="Lovelace",
        )


def test_register_rejects_policy_violation_before_hashing() -> None:
    service, _repo, hasher, _clock, _tokens = _make_auth_service()

    with pytest.raises(PasswordPolicyError):
        service.register(
            email="student@example.edu",
            password="short",
            first_name="Ada",
            last_name="Lovelace",
        )

    with pytest.raises(PasswordPolicyError):
        service.register(
            email="longstudent@example.edu",
            password="longstudent@example.edu",
            first_name="Ada",
            last_name="Lovelace",
        )

    assert hasher.hash_calls == 0


def test_login_issues_access_token_and_rehashes_when_needed() -> None:
    service, repo, hasher, _clock, token_service = _make_auth_service()
    user = repo.create(
        email="student@example.edu",
        hashed_password="old$valid-password-15-chars",
        first_name="Ada",
        last_name="Lovelace",
        role=Role.STUDENT,
        is_active=True,
    )

    result = service.login(
        email="STUDENT@example.edu",
        password="valid-password-15-chars",
        client_ip="127.0.0.1",
    )

    assert result.token_type == "bearer"
    assert result.expires_in == 1800
    parsed = token_service.decode_access_token(result.access_token)
    assert parsed.user_id == user.id
    assert len(repo.password_updates) == 1
    assert user.hashed_password == "fakehash$valid-password-15-chars"
    assert hasher.verify_dummy_calls == 0


def test_login_enumeration_protection_uses_dummy_hash_and_identical_error() -> None:
    service, repo, hasher, _clock, _tokens = _make_auth_service()
    repo.create(
        email="active@example.edu",
        hashed_password="fakehash$valid-password-15-chars",
        first_name="Ada",
        last_name="Lovelace",
        role=Role.STUDENT,
        is_active=True,
    )
    repo.create(
        email="inactive@example.edu",
        hashed_password="fakehash$valid-password-15-chars",
        first_name="Grace",
        last_name="Hopper",
        role=Role.STUDENT,
        is_active=False,
    )

    with pytest.raises(InvalidCredentialsError) as err_missing:
        service.login(
            email="missing@example.edu",
            password="valid-password-15-chars",
            client_ip="127.0.0.1",
        )
    assert hasher.verify_dummy_calls == 1

    with pytest.raises(InvalidCredentialsError) as err_inactive:
        service.login(
            email="inactive@example.edu",
            password="valid-password-15-chars",
            client_ip="127.0.0.1",
        )
    assert hasher.verify_dummy_calls == 2

    with pytest.raises(InvalidCredentialsError) as err_wrong:
        service.login(
            email="active@example.edu",
            password="wrong-password-15-chars",
            client_ip="127.0.0.1",
        )

    assert str(err_missing.value) == str(err_inactive.value) == str(err_wrong.value)


def test_login_safely_handles_empty_and_oversized_passwords_without_hashing_payload() -> None:
    service, repo, hasher, _clock, _tokens = _make_auth_service()
    repo.create(
        email="student@example.edu",
        hashed_password="fakehash$valid-password-15-chars",
        first_name="Ada",
        last_name="Lovelace",
        role=Role.STUDENT,
        is_active=True,
    )

    huge_password = "Z" * 10000
    for bad_password in ("", huge_password):
        with pytest.raises(InvalidCredentialsError):
            service.login(
                email="student@example.edu",
                password=bad_password,
                client_ip="127.0.0.1",
            )

    assert hasher.verify_calls == 0
    assert hasher.verify_dummy_calls == 2
    assert hasher.last_dummy_input != huge_password


def test_login_rate_limit_blocks_before_password_verification() -> None:
    service, repo, hasher, _clock, _tokens = _make_auth_service(
        account_max_attempts=2
    )
    repo.create(
        email="student@example.edu",
        hashed_password="fakehash$valid-password-15-chars",
        first_name="Ada",
        last_name="Lovelace",
        role=Role.STUDENT,
        is_active=True,
    )

    for _ in range(2):
        with pytest.raises(InvalidCredentialsError):
            service.login(
                email="student@example.edu",
                password="wrong-password-15-chars",
                client_ip="127.0.0.1",
            )

    verify_calls_before = hasher.verify_calls
    with pytest.raises(RateLimitExceededError):
        service.login(
            email="student@example.edu",
            password="valid-password-15-chars",
            client_ip="127.0.0.1",
        )
    assert hasher.verify_calls == verify_calls_before
