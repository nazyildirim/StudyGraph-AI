"""Tests for `/api/v1/admin/users` management and last-active-admin protection."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import threading

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.admin_users import router as admin_users_router
from app.api.dependencies.auth import get_token_service, get_user_repository
from app.api.users import router as users_router
from app.authorization.roles import Role
from app.core.security.tokens import MAX_PG_INT32, JwtTokenService
from app.repositories.user_repository import LastActiveAdminError
from tests.fakes import FakeClock, FakeUserRepository

BACKEND_DIR = Path(__file__).resolve().parent.parent
TEST_SECRET = "M" * 48


def _create_admin_client() -> tuple[TestClient, FakeUserRepository, JwtTokenService]:
    clock = FakeClock()
    repo = FakeUserRepository()
    token_service = JwtTokenService(secret_key=TEST_SECRET, clock=clock.utc_now)

    app = FastAPI()
    app.include_router(users_router, prefix="/api/v1")
    app.include_router(admin_users_router, prefix="/api/v1")
    app.dependency_overrides[get_user_repository] = lambda: repo
    app.dependency_overrides[get_token_service] = lambda: token_service
    return TestClient(app), repo, token_service


def test_admin_endpoints_reject_unauthenticated_student_and_instructor() -> None:
    client, repo, token_service = _create_admin_client()
    student = repo.create(
        email="student@example.edu",
        hashed_password="h",
        first_name="S",
        last_name="1",
        role=Role.STUDENT,
    )
    instructor = repo.create(
        email="instructor@example.edu",
        hashed_password="h",
        first_name="I",
        last_name="1",
        role=Role.INSTRUCTOR,
    )
    s_token, _ = token_service.create_access_token(student.id)
    i_token, _ = token_service.create_access_token(instructor.id)

    assert client.get("/api/v1/admin/users").status_code == 401
    assert (
        client.get(
            "/api/v1/admin/users", headers={"Authorization": f"Bearer {s_token}"}
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/v1/admin/users", headers={"Authorization": f"Bearer {i_token}"}
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/admin/users/{student.id}/role",
            headers={"Authorization": f"Bearer {s_token}"},
            json={"role": "admin"},
        ).status_code
        == 403
    )


def test_admin_list_and_get_users_with_filters_and_pagination() -> None:
    client, repo, token_service = _create_admin_client()
    admin = repo.create(
        email="admin@example.edu",
        hashed_password="secret-admin-hash",
        first_name="Admin",
        last_name="One",
        role=Role.ADMIN,
    )
    student1 = repo.create(
        email="s1@example.edu",
        hashed_password="secret-s1-hash",
        first_name="S",
        last_name="1",
        role=Role.STUDENT,
        is_active=True,
    )
    repo.create(
        email="s2@example.edu",
        hashed_password="secret-s2-hash",
        first_name="S",
        last_name="2",
        role=Role.STUDENT,
        is_active=False,
    )
    admin_token, _ = token_service.create_access_token(admin.id)

    resp = client.get(
        "/api/v1/admin/users?role=student&is_active=true&limit=10&offset=0",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == student1.id
    assert "hashed_password" not in resp.text
    assert "secret-s1-hash" not in resp.text

    # Single user lookup and 404
    single = client.get(
        f"/api/v1/admin/users/{student1.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert single.status_code == 200
    assert single.json()["email"] == "s1@example.edu"

    assert (
        client.get(
            "/api/v1/admin/users/9999",
            headers={"Authorization": f"Bearer {admin_token}"},
        ).status_code
        == 404
    )

    # Limit > 100 and invalid path IDs rejected with 422
    assert (
        client.get(
            "/api/v1/admin/users?limit=101",
            headers={"Authorization": f"Bearer {admin_token}"},
        ).status_code
        == 422
    )
    for bad_id in ("0", "-1", str(MAX_PG_INT32 + 1)):
        assert (
            client.get(
                f"/api/v1/admin/users/{bad_id}",
                headers={"Authorization": f"Bearer {admin_token}"},
            ).status_code
            == 422
        )


def test_sole_active_admin_cannot_be_demoted_or_deactivated() -> None:
    client, repo, token_service = _create_admin_client()
    sole_admin = repo.create(
        email="admin@example.edu",
        hashed_password="h",
        first_name="Sole",
        last_name="Admin",
        role=Role.ADMIN,
        is_active=True,
    )
    # An inactive second admin must NOT allow deactivating/demoting the sole active admin!
    repo.create(
        email="inactive-admin@example.edu",
        hashed_password="h",
        first_name="Inactive",
        last_name="Admin",
        role=Role.ADMIN,
        is_active=False,
    )
    token, _ = token_service.create_access_token(sole_admin.id)

    demote = client.patch(
        f"/api/v1/admin/users/{sole_admin.id}/role",
        headers={"Authorization": f"Bearer {token}"},
        json={"role": "student"},
    )
    assert demote.status_code == 409
    assert "LAST_ACTIVE_ADMIN" in demote.json()["detail"]
    assert sole_admin.role == Role.ADMIN.value

    deactivate = client.patch(
        f"/api/v1/admin/users/{sole_admin.id}/status",
        headers={"Authorization": f"Bearer {token}"},
        json={"is_active": False},
    )
    assert deactivate.status_code == 409
    assert "LAST_ACTIVE_ADMIN" in deactivate.json()["detail"]
    assert sole_admin.is_active is True


def test_two_active_admins_allow_demoting_or_deactivating_one_and_revoking_access() -> None:
    client, repo, token_service = _create_admin_client()
    admin1 = repo.create(
        email="admin1@example.edu",
        hashed_password="h",
        first_name="Admin",
        last_name="One",
        role=Role.ADMIN,
    )
    admin2 = repo.create(
        email="admin2@example.edu",
        hashed_password="h",
        first_name="Admin",
        last_name="Two",
        role=Role.ADMIN,
    )
    student = repo.create(
        email="student@example.edu",
        hashed_password="h",
        first_name="S",
        last_name="1",
        role=Role.STUDENT,
    )

    t1, _ = token_service.create_access_token(admin1.id)
    t2, _ = token_service.create_access_token(admin2.id)
    st, _ = token_service.create_access_token(student.id)

    # Promote student -> instructor
    promoted = client.patch(
        f"/api/v1/admin/users/{student.id}/role",
        headers={"Authorization": f"Bearer {t1}"},
        json={"role": "instructor"},
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "instructor"

    # Deactivate student -> student's existing token immediately gets 401 on /users/me
    deact_student = client.patch(
        f"/api/v1/admin/users/{student.id}/status",
        headers={"Authorization": f"Bearer {t1}"},
        json={"is_active": False},
    )
    assert deact_student.status_code == 200
    assert (
        client.get(
            "/api/v1/users/me", headers={"Authorization": f"Bearer {st}"}
        ).status_code
        == 401
    )

    # Deactivate admin2 while admin1 is active -> succeeds (200)
    deact_admin2 = client.patch(
        f"/api/v1/admin/users/{admin2.id}/status",
        headers={"Authorization": f"Bearer {t1}"},
        json={"is_active": False},
    )
    assert deact_admin2.status_code == 200
    assert (
        client.get(
            "/api/v1/admin/users", headers={"Authorization": f"Bearer {t2}"}
        ).status_code
        == 401
    )

    # Now admin1 is the last active admin -> cannot deactivate self (409)
    deact_admin1 = client.patch(
        f"/api/v1/admin/users/{admin1.id}/status",
        headers={"Authorization": f"Bearer {t1}"},
        json={"is_active": False},
    )
    assert deact_admin1.status_code == 409


def test_admin_validation_errors_reject_strict_bool_coercion_and_strip_input() -> None:
    client, repo, token_service = _create_admin_client()
    admin = repo.create(
        email="admin@example.edu",
        hashed_password="h",
        first_name="A",
        last_name="1",
        role=Role.ADMIN,
    )
    student = repo.create(
        email="s@example.edu",
        hashed_password="h",
        first_name="S",
        last_name="1",
        role=Role.STUDENT,
    )
    token, _ = token_service.create_access_token(admin.id)

    bad_status = client.patch(
        f"/api/v1/admin/users/{student.id}/status",
        headers={"Authorization": f"Bearer {token}"},
        json={"is_active": "false"},
    )
    assert bad_status.status_code == 422
    assert all("input" not in err for err in bad_status.json()["detail"])

    bad_role = client.patch(
        f"/api/v1/admin/users/{student.id}/role",
        headers={"Authorization": f"Bearer {token}"},
        json={"role": "superadmin", "extra_field": "nope"},
    )
    assert bad_role.status_code == 422
    assert all("input" not in err for err in bad_role.json()["detail"])
    assert "superadmin" not in bad_role.text
    assert "nope" not in bad_role.text


def test_concurrent_mutual_deactivation_preserves_one_active_admin_in_fake_repo() -> None:
    repo = FakeUserRepository()
    admin1 = repo.create(
        email="a1@example.edu",
        hashed_password="h",
        first_name="A",
        last_name="1",
        role=Role.ADMIN,
    )
    admin2 = repo.create(
        email="a2@example.edu",
        hashed_password="h",
        first_name="A",
        last_name="2",
        role=Role.ADMIN,
    )

    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    outcomes_lock = threading.Lock()

    def worker(target_id: int) -> None:
        barrier.wait()
        try:
            repo.update_status_with_last_admin_guard(target_id, False)
            with outcomes_lock:
                outcomes.append("ok")
        except LastActiveAdminError:
            with outcomes_lock:
                outcomes.append("conflict")

    t1 = threading.Thread(target=worker, args=(admin1.id,))
    t2 = threading.Thread(target=worker, args=(admin2.id,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert sorted(outcomes) == ["conflict", "ok"]
    active_admins = [
        u for u in (admin1, admin2) if u.role == Role.ADMIN.value and u.is_active
    ]
    assert len(active_admins) == 1


def test_phase7_modules_import_cleanly_without_env_or_db(tmp_path: Path) -> None:
    clean_env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(BACKEND_DIR),
    }
    script = (
        "import app.api.routing\n"
        "import app.api.users\n"
        "import app.api.admin_users\n"
        "import app.services.user_profile_service\n"
        "import app.services.admin_user_service\n"
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
