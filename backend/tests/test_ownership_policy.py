"""Tests for non-disclosing `OwnershipPolicy` and `require_resource_access`.

Uses a test-only dummy router and `FakeOwnerResolver`. Real domain resolvers
for future modules (#7/#8) are intentionally not implemented in Issue #6.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.dependencies.auth import (
    get_token_service,
    get_user_repository,
)
from app.api.dependencies.authorization import require_resource_access
from app.authorization.ownership import (
    OwnershipPolicy,
    ResourceNotFoundError,
    ResourceOwnerResolver,
)
from app.authorization.roles import Role
from app.core.security.tokens import MAX_PG_INT32, JwtTokenService
from app.models.user import User
from tests.fakes import FakeClock, FakeOwnerResolver, FakeUserRepository

BACKEND_DIR = Path(__file__).resolve().parent.parent
TEST_SECRET = "O" * 48


def _create_ownership_app(
    owners: dict[int, int],
) -> tuple[TestClient, FakeUserRepository, FakeOwnerResolver, JwtTokenService]:
    clock = FakeClock()
    repo = FakeUserRepository()
    resolver = FakeOwnerResolver(owners)
    token_service = JwtTokenService(secret_key=TEST_SECRET, clock=clock.utc_now)

    def _get_resolver() -> ResourceOwnerResolver:
        return resolver

    app = FastAPI()

    @app.get("/items/{resource_id}")
    def get_item(
        resource_id: int,
        user: User = Depends(require_resource_access(_get_resolver)),
    ) -> dict[str, int]:
        return {"resource_id": resource_id, "user_id": user.id}

    @app.get("/strict-items/{resource_id}")
    def get_strict_item(
        resource_id: int,
        user: User = Depends(
            require_resource_access(_get_resolver, bypass_roles=frozenset())
        ),
    ) -> dict[str, int]:
        return {"resource_id": resource_id, "user_id": user.id}

    app.dependency_overrides[get_user_repository] = lambda: repo
    app.dependency_overrides[get_token_service] = lambda: token_service
    return TestClient(app), repo, resolver, token_service


def test_ownership_policy_unit_deny_by_default() -> None:
    policy = OwnershipPolicy()
    student = User(
        id=10,
        email="s@e.edu",
        hashed_password="h",
        first_name="S",
        last_name="U",
        role=Role.STUDENT.value,
        is_active=True,
    )
    admin = User(
        id=1,
        email="a@e.edu",
        hashed_password="h",
        first_name="A",
        last_name="U",
        role=Role.ADMIN.value,
        is_active=True,
    )

    policy.check(student, owner_id=10)
    policy.check(admin, owner_id=10)

    with pytest.raises(ResourceNotFoundError):
        policy.check(student, owner_id=99)
    with pytest.raises(ResourceNotFoundError):
        policy.check(student, owner_id=None)
    with pytest.raises(ResourceNotFoundError):
        policy.check(admin, owner_id=None)
    with pytest.raises(ResourceNotFoundError):
        policy.check(admin, owner_id=10, bypass_roles=frozenset())


def test_non_owner_and_non_existent_resource_return_identical_404() -> None:
    client, repo, _resolver, token_service = _create_ownership_app(
        owners={100: 1, 200: 2}
    )
    student1 = repo.create(
        email="s1@example.edu",
        hashed_password="h",
        first_name="S",
        last_name="1",
        role=Role.STUDENT,
    )
    student2 = repo.create(
        email="s2@example.edu",
        hashed_password="h",
        first_name="S",
        last_name="2",
        role=Role.STUDENT,
    )
    instructor = repo.create(
        email="inst@example.edu",
        hashed_password="h",
        first_name="I",
        last_name="1",
        role=Role.INSTRUCTOR,
    )
    admin = repo.create(
        email="admin@example.edu",
        hashed_password="h",
        first_name="A",
        last_name="1",
        role=Role.ADMIN,
    )

    s1_token, _ = token_service.create_access_token(student1.id)
    s2_token, _ = token_service.create_access_token(student2.id)
    inst_token, _ = token_service.create_access_token(instructor.id)
    admin_token, _ = token_service.create_access_token(admin.id)

    # Owner succeeds
    assert client.get(
        "/items/100", headers={"Authorization": f"Bearer {s1_token}"}
    ).status_code == 200

    # Admin bypass succeeds on existing resource, gets 404 on missing resource
    assert client.get(
        "/items/100", headers={"Authorization": f"Bearer {admin_token}"}
    ).status_code == 200
    assert client.get(
        "/items/999", headers={"Authorization": f"Bearer {admin_token}"}
    ).status_code == 404

    # Strict route with empty bypass_roles denies even admin (404)
    assert client.get(
        "/strict-items/100", headers={"Authorization": f"Bearer {admin_token}"}
    ).status_code == 404

    # Non-owner student, non-owner instructor, and missing resource -> identical 404
    resp_other_student = client.get(
        "/items/100", headers={"Authorization": f"Bearer {s2_token}"}
    )
    resp_other_instructor = client.get(
        "/items/100", headers={"Authorization": f"Bearer {inst_token}"}
    )
    resp_missing = client.get(
        "/items/999", headers={"Authorization": f"Bearer {s2_token}"}
    )

    for resp in (resp_other_student, resp_other_instructor, resp_missing):
        assert resp.status_code == 404

    assert resp_other_student.json() == resp_missing.json() == {"detail": "Resource not found."}
    assert resp_other_instructor.json() == resp_missing.json()
    assert dict(resp_other_student.headers) == dict(resp_missing.headers)


def test_ownership_reflects_live_db_role_change_for_existing_token() -> None:
    client, repo, _resolver, token_service = _create_ownership_app(owners={100: 1})
    owner = repo.create(
        email="owner@example.edu",
        hashed_password="h",
        first_name="O",
        last_name="1",
        role=Role.STUDENT,
    )
    other = repo.create(
        email="other@example.edu",
        hashed_password="h",
        first_name="S",
        last_name="2",
        role=Role.STUDENT,
    )
    assert owner.id == 1

    other_token, _ = token_service.create_access_token(other.id)
    assert client.get(
        "/items/100", headers={"Authorization": f"Bearer {other_token}"}
    ).status_code == 404

    # Promote to admin in DB -> same token now passes admin bypass
    other.role = Role.ADMIN.value
    assert client.get(
        "/items/100", headers={"Authorization": f"Bearer {other_token}"}
    ).status_code == 200

    # Demote back to student -> immediately 404 again
    other.role = Role.STUDENT.value
    assert client.get(
        "/items/100", headers={"Authorization": f"Bearer {other_token}"}
    ).status_code == 404


@pytest.mark.parametrize("bad_id", ["0", "-1", str(MAX_PG_INT32 + 1), "abc"])
def test_invalid_resource_id_path_values_return_422(bad_id: str) -> None:
    client, repo, resolver, token_service = _create_ownership_app(owners={100: 1})
    user = repo.create(
        email="u@example.edu",
        hashed_password="h",
        first_name="U",
        last_name="1",
        role=Role.ADMIN,
    )
    token, _ = token_service.create_access_token(user.id)

    resp = client.get(
        f"/items/{bad_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 422
    assert resolver.lookup_calls == []


def test_phase6_modules_import_cleanly_without_env_or_db(tmp_path: Path) -> None:
    clean_env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(BACKEND_DIR),
    }
    script = (
        "import app.authorization.ownership\n"
        "import app.api.dependencies.authorization\n"
        "import app.api.dependencies.auth\n"
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
