"""Tests for `/api/v1/users/me` profile retrieval and allowlisted updates."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.dependencies.auth import get_token_service, get_user_repository
from app.api.users import router as users_router
from app.authorization.roles import Role
from app.core.security.tokens import JwtTokenService
from app.services.user_profile_service import UserProfileService
from tests.fakes import FakeClock, FakeUserRepository

TEST_SECRET = "P" * 48


def _create_profile_client() -> tuple[TestClient, FakeUserRepository, JwtTokenService]:
    clock = FakeClock()
    repo = FakeUserRepository()
    token_service = JwtTokenService(secret_key=TEST_SECRET, clock=clock.utc_now)

    app = FastAPI()
    app.include_router(users_router, prefix="/api/v1")
    app.dependency_overrides[get_user_repository] = lambda: repo
    app.dependency_overrides[get_token_service] = lambda: token_service
    return TestClient(app), repo, token_service


def test_get_me_requires_authentication_and_omits_password_hash() -> None:
    client, repo, token_service = _create_profile_client()
    user = repo.create(
        email="student@example.edu",
        hashed_password="secret-argon2-hash-value",
        first_name="Ada",
        last_name="Lovelace",
        role=Role.STUDENT,
    )
    token, _ = token_service.create_access_token(user.id)

    assert client.get("/api/v1/users/me").status_code == 401

    resp = client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == user.id
    assert body["email"] == "student@example.edu"
    assert body["first_name"] == "Ada"
    assert body["last_name"] == "Lovelace"
    assert body["role"] == "student"
    assert body["is_active"] is True
    assert "hashed_password" not in body
    assert "secret-argon2-hash-value" not in resp.text


def test_patch_me_updates_allowlisted_name_fields_only() -> None:
    client, repo, token_service = _create_profile_client()
    user = repo.create(
        email="student@example.edu",
        hashed_password="hash",
        first_name="Ada",
        last_name="Lovelace",
        role=Role.STUDENT,
    )
    token, _ = token_service.create_access_token(user.id)

    resp1 = client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"first_name": "  Augusta  "},
    )
    assert resp1.status_code == 200
    assert resp1.json()["first_name"] == "Augusta"
    assert resp1.json()["last_name"] == "Lovelace"

    resp2 = client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"last_name": "  King  "},
    )
    assert resp2.status_code == 200
    assert resp2.json()["first_name"] == "Augusta"
    assert resp2.json()["last_name"] == "King"
    assert user.role == Role.STUDENT.value
    assert user.is_active is True


@pytest.mark.parametrize(
    "forbidden_payload",
    [
        {"role": "admin"},
        {"first_name": "New", "role": "admin"},
        {"is_active": False},
        {"email": "hacker@example.edu"},
        {"password": "MySecretPassword15!"},
        {"hashed_password": "fake-hash-value"},
        {"id": 999},
    ],
)
def test_patch_me_rejects_forbidden_fields_and_does_not_echo_input(
    forbidden_payload: dict[str, object],
) -> None:
    client, repo, token_service = _create_profile_client()
    user = repo.create(
        email="student@example.edu",
        hashed_password="original-hash",
        first_name="Ada",
        last_name="Lovelace",
        role=Role.STUDENT,
        is_active=True,
    )
    token, _ = token_service.create_access_token(user.id)

    resp = client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json=forbidden_payload,
    )
    assert resp.status_code == 422
    assert all("input" not in err for err in resp.json()["detail"])
    assert "MySecretPassword15!" not in resp.text

    # DB record must remain completely unchanged.
    assert user.id == 1
    assert user.email == "student@example.edu"
    assert user.role == Role.STUDENT.value
    assert user.is_active is True
    assert user.hashed_password == "original-hash"
    assert user.first_name == "Ada"


@pytest.mark.parametrize(
    "invalid_payload",
    [
        {},
        {"first_name": "   "},
        {"last_name": ""},
        {"first_name": "A" * 101},
        {"first_name": 12345},
    ],
)
def test_patch_me_rejects_empty_blank_and_oversized_names(
    invalid_payload: dict[str, object],
) -> None:
    client, repo, token_service = _create_profile_client()
    user = repo.create(
        email="student@example.edu",
        hashed_password="hash",
        first_name="Ada",
        last_name="Lovelace",
        role=Role.STUDENT,
    )
    token, _ = token_service.create_access_token(user.id)

    resp = client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json=invalid_payload,
    )
    assert resp.status_code == 422
    assert all("input" not in err for err in resp.json()["detail"])


def test_user_profile_service_enforces_second_layer_allowlist() -> None:
    repo = FakeUserRepository()
    user = repo.create(
        email="student@example.edu",
        hashed_password="hash",
        first_name="Ada",
        last_name="Lovelace",
        role=Role.STUDENT,
    )
    service = UserProfileService(user_repository=repo)

    with pytest.raises(ValueError):
        service.update_profile(user)

    with pytest.raises(ValueError):
        repo.update_profile_fields(user.id, {"role": "admin"})
