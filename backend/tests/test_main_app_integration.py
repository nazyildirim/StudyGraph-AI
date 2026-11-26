"""Integration tests for the main FastAPI application (`app.main.app`)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.dependencies.auth import (
    get_login_rate_limiter,
    get_password_hasher,
    get_token_service,
    get_user_repository,
)
from app.authorization.roles import Role
from app.core.security.rate_limit import InMemoryLoginRateLimiter
from app.core.security.tokens import JwtTokenService
from app.main import app
from tests.fakes import FakeClock, FakePasswordHasher, FakeUserRepository

TEST_SECRET = "M" * 48


def test_main_app_openapi_and_swagger_expose_all_expected_routes_without_prefix_duplication() -> None:
    client = TestClient(app)

    docs_resp = client.get("/docs")
    assert docs_resp.status_code == 200

    openapi_resp = client.get("/openapi.json")
    assert openapi_resp.status_code == 200
    paths = openapi_resp.json()["paths"]

    expected_routes = {
        "/api/v1/health": {"get"},
        "/api/v1/learning-analyses": {"post"},
        "/api/v1/auth/register": {"post"},
        "/api/v1/auth/login": {"post"},
        "/api/v1/users/me": {"get", "patch"},
        "/api/v1/admin/users": {"get"},
        "/api/v1/admin/users/{user_id}": {"get"},
        "/api/v1/admin/users/{user_id}/role": {"patch"},
        "/api/v1/admin/users/{user_id}/status": {"patch"},
    }

    for path, methods in expected_routes.items():
        assert path in paths, f"Missing expected route in OpenAPI: {path}"
        assert methods <= set(paths[path].keys())

    # Ensure no duplicated prefixes exist anywhere in OpenAPI paths.
    for path in paths:
        assert "/api/v1/api/v1" not in path
        assert "/auth/auth" not in path
        assert "/users/users" not in path
        assert "/admin/users/admin/users" not in path


def test_main_app_auth_authz_and_existing_routes_work_together() -> None:
    clock = FakeClock()
    repo = FakeUserRepository()
    hasher = FakePasswordHasher()
    token_service = JwtTokenService(secret_key=TEST_SECRET, clock=clock.utc_now)
    rate_limiter = InMemoryLoginRateLimiter(clock=clock.monotonic)

    admin = repo.create(
        email="admin@example.edu",
        hashed_password=hasher.hash("MainAppAdminSecret15!"),
        first_name="Root",
        last_name="Admin",
        role=Role.ADMIN,
    )

    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_user_repository] = lambda: repo
    app.dependency_overrides[get_password_hasher] = lambda: hasher
    app.dependency_overrides[get_token_service] = lambda: token_service
    app.dependency_overrides[get_login_rate_limiter] = lambda: rate_limiter

    try:
        client = TestClient(app)

        # Existing health route works
        assert client.get("/api/v1/health").status_code == 200

        # Unauthenticated requests to protected routes return 401
        assert client.get("/api/v1/users/me").status_code == 401
        assert client.get("/api/v1/admin/users").status_code == 401

        # Student registers, logs in, accesses /users/me (200), gets 403 on /admin/users
        reg = client.post(
            "/api/v1/auth/register",
            json={
                "email": "student@example.edu",
                "password": "MainAppStudentPass15!",
                "first_name": "Ada",
                "last_name": "Lovelace",
            },
        )
        assert reg.status_code == 201

        login = client.post(
            "/api/v1/auth/login",
            json={
                "email": "student@example.edu",
                "password": "MainAppStudentPass15!",
            },
        )
        assert login.status_code == 200
        student_token = login.json()["access_token"]

        assert (
            client.get(
                "/api/v1/users/me",
                headers={"Authorization": f"Bearer {student_token}"},
            ).status_code
            == 200
        )
        assert (
            client.get(
                "/api/v1/admin/users",
                headers={"Authorization": f"Bearer {student_token}"},
            ).status_code
            == 403
        )

        # Admin accesses /admin/users (200)
        admin_token, _ = token_service.create_access_token(admin.id)
        admin_resp = client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert admin_resp.status_code == 200
        assert admin_resp.json()["total"] == 2
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
