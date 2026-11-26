"""HTTP API tests for /api/v1/auth/register and /api/v1/auth/login.

Mounted on an isolated FastAPI() instance (without modifying app/main.py)
using dependency_overrides and in-memory fakes so tests run without PostgreSQL
or .env files.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import router as auth_router
from app.api.dependencies.auth import get_auth_service
from app.authorization.roles import Role
from app.core.security.passwords import PasswordPolicy
from app.core.security.rate_limit import InMemoryLoginRateLimiter
from app.core.security.tokens import JwtTokenService
from app.services.auth_service import AuthService
from tests.fakes import FakeClock, FakePasswordHasher, FakeUserRepository

BACKEND_DIR = Path(__file__).resolve().parent.parent
TEST_JWT_SECRET = "A" * 48


def _create_test_client(
    *,
    account_max_attempts: int = 5,
) -> tuple[TestClient, FakeUserRepository, FakePasswordHasher, FakeClock, JwtTokenService]:
    clock = FakeClock()
    repo = FakeUserRepository()
    hasher = FakePasswordHasher()
    token_service = JwtTokenService(
        secret_key=TEST_JWT_SECRET,
        clock=clock.utc_now,
    )
    rate_limiter = InMemoryLoginRateLimiter(
        account_max_attempts=account_max_attempts,
        ip_max_attempts=30,
        window_seconds=900,
        clock=clock.monotonic,
    )
    service = AuthService(
        user_repository=repo,
        password_hasher=hasher,
        password_policy=PasswordPolicy(),
        token_service=token_service,
        rate_limiter=rate_limiter,
    )

    test_app = FastAPI()
    test_app.include_router(auth_router, prefix="/api/v1")
    test_app.dependency_overrides[get_auth_service] = lambda: service

    return TestClient(test_app), repo, hasher, clock, token_service


def test_register_success_and_never_returns_password_or_token() -> None:
    client, _repo, _hasher, _clock, _tokens = _create_test_client()
    secret_pw = "MySuperSecretPassword15!"

    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "  Student@Example.EDU ",
            "password": secret_pw,
            "first_name": "  Ada ",
            "last_name": " Lovelace  ",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "student@example.edu"
    assert body["first_name"] == "Ada"
    assert body["last_name"] == "Lovelace"
    assert body["role"] == "student"
    assert body["is_active"] is True
    assert "hashed_password" not in body
    assert "password" not in body
    assert "access_token" not in body
    assert secret_pw not in response.text


def test_register_rejects_extra_fields_and_does_not_echo_password() -> None:
    client, _repo, _hasher, _clock, _tokens = _create_test_client()
    secret_pw = "SensitivePasswordShouldNotLeak15!"

    # Extra forbidden field (privilege escalation attempt)
    resp_extra = client.post(
        "/api/v1/auth/register",
        json={
            "email": "student@example.edu",
            "password": secret_pw,
            "first_name": "Ada",
            "last_name": "Lovelace",
            "role": "admin",
        },
    )
    assert resp_extra.status_code == 422
    assert secret_pw not in resp_extra.text

    # Invalid sibling field (blank first_name) must not echo password
    resp_name = client.post(
        "/api/v1/auth/register",
        json={
            "email": "student@example.edu",
            "password": secret_pw,
            "first_name": "   ",
            "last_name": "Lovelace",
        },
    )
    assert resp_name.status_code == 422
    assert secret_pw not in resp_name.text

    # Short password rejected by PasswordPolicy must not echo password
    short_pw = "TooShort123"
    resp_short = client.post(
        "/api/v1/auth/register",
        json={
            "email": "student@example.edu",
            "password": short_pw,
            "first_name": "Ada",
            "last_name": "Lovelace",
        },
    )
    assert resp_short.status_code == 422
    assert short_pw not in resp_short.text

    # Non-string password rejected by Pydantic must not echo secret input
    resp_bad_type = client.post(
        "/api/v1/auth/register",
        json={
            "email": "student@example.edu",
            "password": ["SecretListLeak15!"],
            "first_name": "Ada",
            "last_name": "Lovelace",
        },
    )
    assert resp_bad_type.status_code == 422
    assert "SecretListLeak15!" not in resp_bad_type.text

    # Missing required field alongside a valid password must not echo password
    resp_missing_email = client.post(
        "/api/v1/auth/register",
        json={
            "password": secret_pw,
            "first_name": "Ada",
            "last_name": "Lovelace",
        },
    )
    assert resp_missing_email.status_code == 422
    assert secret_pw not in resp_missing_email.text

    # Numeric password rejected by Pydantic must not echo numeric input
    resp_int_pw = client.post(
        "/api/v1/auth/login",
        json={
            "email": "student@example.edu",
            "password": 999888777666555,
        },
    )
    assert resp_int_pw.status_code == 422
    assert "999888777666555" not in resp_int_pw.text

    # Missing email on login alongside a valid password must not echo password
    resp_login_missing = client.post(
        "/api/v1/auth/login",
        json={"password": secret_pw},
    )
    assert resp_login_missing.status_code == 422
    assert secret_pw not in resp_login_missing.text


def test_register_duplicate_email_case_insensitive_returns_409() -> None:
    client, _repo, _hasher, _clock, _tokens = _create_test_client()

    first = client.post(
        "/api/v1/auth/register",
        json={
            "email": "student@example.edu",
            "password": "ValidPasswordFifteen15!",
            "first_name": "Ada",
            "last_name": "Lovelace",
        },
    )
    assert first.status_code == 201

    second = client.post(
        "/api/v1/auth/register",
        json={
            "email": "STUDENT@EXAMPLE.EDU",
            "password": "AnotherValidPassword15!",
            "first_name": "Grace",
            "last_name": "Hopper",
        },
    )
    assert second.status_code == 409
    assert "access_token" not in second.text


def test_register_and_login_preserve_password_whitespace() -> None:
    client, _repo, _hasher, _clock, _tokens = _create_test_client()
    padded_pw = "  padded-secret-15  "

    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": "space@example.edu",
            "password": padded_pw,
            "first_name": "Ada",
            "last_name": "Lovelace",
        },
    )
    assert reg.status_code == 201

    login_trimmed = client.post(
        "/api/v1/auth/login",
        json={"email": "space@example.edu", "password": padded_pw.strip()},
    )
    assert login_trimmed.status_code == 401

    login_exact = client.post(
        "/api/v1/auth/login",
        json={"email": "SPACE@EXAMPLE.EDU", "password": padded_pw},
    )
    assert login_exact.status_code == 200
    body = login_exact.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 1800
    assert isinstance(body["access_token"], str) and body["access_token"]


def test_login_returns_identical_401_for_missing_wrong_inactive_and_oversized_pw() -> None:
    client, repo, _hasher, _clock, _tokens = _create_test_client(
        account_max_attempts=10
    )
    repo.create(
        email="active@example.edu",
        hashed_password="fakehash$ValidPasswordFifteen15!",
        first_name="Ada",
        last_name="Lovelace",
        role=Role.STUDENT,
        is_active=True,
    )
    repo.create(
        email="inactive@example.edu",
        hashed_password="fakehash$ValidPasswordFifteen15!",
        first_name="Grace",
        last_name="Hopper",
        role=Role.STUDENT,
        is_active=False,
    )

    huge_pw = "Q" * 5000
    responses = [
        client.post(
            "/api/v1/auth/login",
            json={"email": "unknown@example.edu", "password": "ValidPasswordFifteen15!"},
        ),
        client.post(
            "/api/v1/auth/login",
            json={"email": "active@example.edu", "password": "WrongPasswordFifteen15!"},
        ),
        client.post(
            "/api/v1/auth/login",
            json={"email": "inactive@example.edu", "password": "ValidPasswordFifteen15!"},
        ),
        client.post(
            "/api/v1/auth/login",
            json={"email": "active@example.edu", "password": ""},
        ),
        client.post(
            "/api/v1/auth/login",
            json={"email": "active@example.edu", "password": huge_pw},
        ),
    ]

    details = set()
    for resp in responses:
        assert resp.status_code == 401
        assert resp.headers.get("www-authenticate") == "Bearer"
        assert "access_token" not in resp.text
        assert huge_pw not in resp.text
        details.add(resp.json()["detail"])

    assert len(details) == 1


def test_login_rate_limit_returns_429_with_retry_after() -> None:
    client, repo, _hasher, _clock, _tokens = _create_test_client(
        account_max_attempts=5
    )
    repo.create(
        email="student@example.edu",
        hashed_password="fakehash$ValidPasswordFifteen15!",
        first_name="Ada",
        last_name="Lovelace",
        role=Role.STUDENT,
        is_active=True,
    )

    for _ in range(5):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "student@example.edu", "password": "WrongPassword15!"},
        )
        assert resp.status_code == 401

    limited = client.post(
        "/api/v1/auth/login",
        json={"email": "student@example.edu", "password": "ValidPasswordFifteen15!"},
    )
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1
    assert "access_token" not in limited.text


def test_login_rejects_extra_fields_without_echoing_password() -> None:
    client, _repo, _hasher, _clock, _tokens = _create_test_client()
    secret_pw = "DoNotEchoThisLoginSecret15!"

    resp = client.post(
        "/api/v1/auth/login",
        json={
            "email": "student@example.edu",
            "password": secret_pw,
            "remember_me": True,
        },
    )
    assert resp.status_code == 422
    assert secret_pw not in resp.text


def test_phase5_modules_import_cleanly_without_env_or_db(tmp_path: Path) -> None:
    clean_env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(BACKEND_DIR),
    }
    script = (
        "import app.core.security.email\n"
        "import app.repositories.user_repository\n"
        "import app.schemas.auth\n"
        "import app.schemas.user\n"
        "import app.services.auth_service\n"
        "import app.api.dependencies.auth\n"
        "import app.api.auth\n"
        "import app.database as db_module\n"
        "assert db_module._engine is None\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=clean_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"Subprocess failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
