"""Tests for deny-by-default `require_roles` authorization dependency."""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import (
    get_token_service,
    get_user_repository,
)
from app.api.dependencies.authorization import require_roles
from app.authorization.roles import Role
from app.core.security.tokens import JwtTokenService
from app.models.user import User
from tests.fakes import FakeClock, FakeUserRepository

TEST_SECRET = "R" * 48


def _create_role_app() -> tuple[TestClient, FakeUserRepository, JwtTokenService]:
    clock = FakeClock()
    repo = FakeUserRepository()
    token_service = JwtTokenService(secret_key=TEST_SECRET, clock=clock.utc_now)

    app = FastAPI()

    @app.get("/admin-only")
    def admin_only(
        user: User = Depends(require_roles(Role.ADMIN)),
    ) -> dict[str, object]:
        return {"user_id": user.id, "role": user.role}

    @app.get("/staff-only")
    def staff_only(
        user: User = Depends(require_roles(Role.INSTRUCTOR, Role.ADMIN)),
    ) -> dict[str, object]:
        return {"user_id": user.id, "role": user.role}

    @app.get("/empty-roles")
    def empty_roles(
        user: User = Depends(require_roles()),
    ) -> dict[str, object]:
        return {"user_id": user.id}

    app.dependency_overrides[get_user_repository] = lambda: repo
    app.dependency_overrides[get_token_service] = lambda: token_service
    return TestClient(app), repo, token_service


def test_role_authorization_enforces_db_roles_and_deny_by_default() -> None:
    client, repo, token_service = _create_role_app()

    student = repo.create(
        email="student@example.edu",
        hashed_password="hash",
        first_name="S",
        last_name="One",
        role=Role.STUDENT,
    )
    instructor = repo.create(
        email="instructor@example.edu",
        hashed_password="hash",
        first_name="I",
        last_name="One",
        role=Role.INSTRUCTOR,
    )
    admin = repo.create(
        email="admin@example.edu",
        hashed_password="hash",
        first_name="A",
        last_name="One",
        role=Role.ADMIN,
    )

    student_token, _ = token_service.create_access_token(student.id)
    instructor_token, _ = token_service.create_access_token(instructor.id)
    admin_token, _ = token_service.create_access_token(admin.id)

    # Admin-only route
    assert client.get(
        "/admin-only", headers={"Authorization": f"Bearer {student_token}"}
    ).status_code == 403
    assert client.get(
        "/admin-only", headers={"Authorization": f"Bearer {instructor_token}"}
    ).status_code == 403
    assert client.get(
        "/admin-only", headers={"Authorization": f"Bearer {admin_token}"}
    ).status_code == 200

    # Multi-role route
    assert client.get(
        "/staff-only", headers={"Authorization": f"Bearer {student_token}"}
    ).status_code == 403
    assert client.get(
        "/staff-only", headers={"Authorization": f"Bearer {instructor_token}"}
    ).status_code == 200
    assert client.get(
        "/staff-only", headers={"Authorization": f"Bearer {admin_token}"}
    ).status_code == 200

    # Empty allowed roles -> deny by default even for admin
    assert client.get(
        "/empty-roles", headers={"Authorization": f"Bearer {admin_token}"}
    ).status_code == 403


def test_role_downgrade_in_db_immediately_revokes_access_for_existing_token() -> None:
    client, repo, token_service = _create_role_app()
    admin = repo.create(
        email="admin@example.edu",
        hashed_password="hash",
        first_name="A",
        last_name="One",
        role=Role.ADMIN,
    )
    token, _ = token_service.create_access_token(admin.id)

    assert client.get(
        "/admin-only", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 200

    # Demote in DB -> same token immediately gets 403.
    admin.role = Role.STUDENT.value
    assert client.get(
        "/admin-only", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 403
