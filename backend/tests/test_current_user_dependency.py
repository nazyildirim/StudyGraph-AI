"""Tests for `get_current_user` authentication dependency (DB-backed checks)."""

from __future__ import annotations

from uuid import uuid4

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import jwt

from app.api.dependencies.auth import (
    get_current_user,
    get_token_service,
    get_user_repository,
)
from app.authorization.roles import Role
from app.core.security.tokens import JwtTokenService
from app.models.user import User
from tests.fakes import FakeClock, FakeUserRepository

TEST_SECRET = "C" * 48


def _create_app() -> tuple[TestClient, FakeUserRepository, FakeClock, JwtTokenService]:
    clock = FakeClock()
    repo = FakeUserRepository()
    token_service = JwtTokenService(secret_key=TEST_SECRET, clock=clock.utc_now)

    app = FastAPI()

    @app.get("/protected")
    def protected_route(current_user: User = Depends(get_current_user)) -> dict[str, object]:
        return {
            "id": current_user.id,
            "role": current_user.role,
            "is_active": current_user.is_active,
        }

    app.dependency_overrides[get_user_repository] = lambda: repo
    app.dependency_overrides[get_token_service] = lambda: token_service
    return TestClient(app), repo, clock, token_service


def test_valid_token_returns_db_user_and_reflects_live_role_changes() -> None:
    client, repo, _clock, token_service = _create_app()
    user = repo.create(
        email="student@example.edu",
        hashed_password="hash",
        first_name="Ada",
        last_name="Lovelace",
        role=Role.STUDENT,
        is_active=True,
    )
    token, _ = token_service.create_access_token(user.id)

    resp1 = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp1.status_code == 200
    assert resp1.json() == {"id": user.id, "role": "student", "is_active": True}

    # Change role in DB without issuing a new token -> next request sees DB role immediately.
    user.role = Role.INSTRUCTOR.value
    resp2 = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp2.status_code == 200
    assert resp2.json()["role"] == "instructor"


def test_forged_role_claim_inside_jwt_is_ignored_in_favor_of_db_role() -> None:
    client, repo, clock, _token_service = _create_app()
    user = repo.create(
        email="student@example.edu",
        hashed_password="hash",
        first_name="Ada",
        last_name="Lovelace",
        role=Role.STUDENT,
        is_active=True,
    )
    now_ts = int(clock.utc_now().timestamp())
    token_with_role_claim = jwt.encode(
        {
            "sub": str(user.id),
            "type": "access",
            "role": "admin",  # attacker-injected claim must never be trusted
            "iss": "studygraph-ai",
            "aud": "studygraph-ai-api",
            "iat": now_ts,
            "nbf": now_ts,
            "exp": now_ts + 1800,
            "jti": str(uuid4()),
        },
        TEST_SECRET,
        algorithm="HS256",
    )

    resp = client.get(
        "/protected",
        headers={"Authorization": f"Bearer {token_with_role_claim}"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "student"


def test_inactive_deleted_and_corrupted_role_users_are_rejected_with_401() -> None:
    client, repo, _clock, token_service = _create_app()
    user = repo.create(
        email="user@example.edu",
        hashed_password="hash",
        first_name="Ada",
        last_name="Lovelace",
        role=Role.STUDENT,
        is_active=True,
    )
    token, _ = token_service.create_access_token(user.id)

    # Deactivated user -> 401
    user.is_active = False
    resp_inactive = client.get(
        "/protected", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp_inactive.status_code == 401
    assert resp_inactive.headers.get("www-authenticate") == "Bearer"

    # Reactivate with invalid/corrupted role in DB -> deny by default (401)
    user.is_active = True
    user.role = "superadmin"
    resp_bad_role = client.get(
        "/protected", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp_bad_role.status_code == 401

    # Deleted user -> 401
    repo.delete(user.id)
    resp_deleted = client.get(
        "/protected", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp_deleted.status_code == 401
    assert resp_deleted.headers.get("www-authenticate") == "Bearer"


def test_missing_malformed_and_expired_tokens_return_401_without_token_echo() -> None:
    client, repo, clock, token_service = _create_app()
    user = repo.create(
        email="user@example.edu",
        hashed_password="hash",
        first_name="Ada",
        last_name="Lovelace",
        role=Role.STUDENT,
        is_active=True,
    )
    token, _ = token_service.create_access_token(user.id)

    for headers in (
        {},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer not.a.jwt"},
        {"Authorization": f"Bearer {token} extra"},
    ):
        resp = client.get("/protected", headers=headers)
        assert resp.status_code == 401
        assert resp.headers.get("www-authenticate") == "Bearer"
        assert token not in resp.text

    # Advance past 30-minute lifetime -> 401
    clock.advance(1801)
    resp_expired = client.get(
        "/protected", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp_expired.status_code == 401
    assert token not in resp_expired.text
