"""End-to-end PostgreSQL integration tests for auth, profile, admin, and CLI."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.admin_users import router as admin_users_router
from app.api.auth import router as auth_router
from app.api.dependencies.auth import (
    get_login_rate_limiter,
    get_password_hasher,
    get_token_service,
)
from app.api.users import router as users_router
from app.core.security.passwords import Argon2PasswordHasher
from app.core.security.rate_limit import InMemoryLoginRateLimiter
from app.core.security.tokens import JwtTokenService
from app.database import get_db

pytestmark = pytest.mark.postgres
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
TEST_JWT_SECRET = "E" * 48


def _create_pg_client(
    pg_session_factory: sessionmaker[Session],
) -> TestClient:
    hasher = Argon2PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
    token_service = JwtTokenService(secret_key=TEST_JWT_SECRET)
    rate_limiter = InMemoryLoginRateLimiter(
        account_max_attempts=5,
        ip_max_attempts=30,
        window_seconds=900,
    )

    def _override_get_db():
        session = pg_session_factory()
        try:
            yield session
        finally:
            session.close()

    app = FastAPI()
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(users_router, prefix="/api/v1")
    app.include_router(admin_users_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_password_hasher] = lambda: hasher
    app.dependency_overrides[get_token_service] = lambda: token_service
    app.dependency_overrides[get_login_rate_limiter] = lambda: rate_limiter
    return TestClient(app)


def _run_cli_subprocess(
    args: list[str],
    *,
    stdin_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(BACKEND_DIR),
        "DATABASE_URL": os.environ["TEST_DATABASE_URL"],
        "ARGON2_TIME_COST": "2",
        "ARGON2_MEMORY_COST": "19456",
        "ARGON2_PARALLELISM": "1",
    }
    return subprocess.run(
        [sys.executable, "-m", "app.cli.create_admin", *args],
        cwd=BACKEND_DIR,
        env=env,
        input=stdin_text,
        capture_output=True,
        text=True,
        check=False,
    )


def test_e2e_register_login_profile_role_change_and_deactivation_on_postgres(
    pg_session_factory: sessionmaker[Session],
    clean_users_table: None,
) -> None:
    client = _create_pg_client(pg_session_factory)

    # 1. CLI creates initial admin in PostgreSQL (Scenario 1).
    cli_ok = _run_cli_subprocess(
        [
            "--email",
            "Admin@Example.Edu",
            "--first-name",
            "Root",
            "--last-name",
            "Admin",
            "--password-stdin",
        ],
        stdin_text="InitialAdminSecret15!\n",
    )
    assert cli_ok.returncode == 0, cli_ok.stderr
    assert "InitialAdminSecret15!" not in cli_ok.stdout

    # 2. Admin logs in and accesses /api/v1/admin/users.
    admin_login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.edu", "password": "InitialAdminSecret15!"},
    )
    assert admin_login.status_code == 200
    admin_token = admin_login.json()["access_token"]

    list_resp = client.get(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] == 1

    # 3. Student self-registers, logs in, reads and updates profile.
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": "Student@Example.Edu",
            "password": "StudentValidPassword15!",
            "first_name": "Ada",
            "last_name": "Lovelace",
        },
    )
    assert reg.status_code == 201
    student_id = reg.json()["id"]

    student_login = client.post(
        "/api/v1/auth/login",
        json={"email": "student@example.edu", "password": "StudentValidPassword15!"},
    )
    assert student_login.status_code == 200
    student_token = student_login.json()["access_token"]

    me_patch = client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {student_token}"},
        json={"first_name": "Augusta"},
    )
    assert me_patch.status_code == 200
    assert me_patch.json()["first_name"] == "Augusta"

    # 4. Admin promotes student to admin -> student's existing token now accesses /admin/users.
    assert (
        client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {student_token}"},
        ).status_code
        == 403
    )
    promote_resp = client.patch(
        f"/api/v1/admin/users/{student_id}/role",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"role": "admin"},
    )
    assert promote_resp.status_code == 200
    assert (
        client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {student_token}"},
        ).status_code
        == 200
    )

    # 5. Admin demotes student back to student -> existing token immediately gets 403.
    demote_resp = client.patch(
        f"/api/v1/admin/users/{student_id}/role",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"role": "student"},
    )
    assert demote_resp.status_code == 200
    assert (
        client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {student_token}"},
        ).status_code
        == 403
    )

    # 6. Admin deactivates student -> existing token immediately gets 401 on /users/me.
    deact_resp = client.patch(
        f"/api/v1/admin/users/{student_id}/status",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"is_active": False},
    )
    assert deact_resp.status_code == 200
    assert (
        client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {student_token}"},
        ).status_code
        == 401
    )


def test_cli_duplicate_promote_active_and_reject_inactive_on_postgres(
    migrated_pg_engine: Engine,
    pg_session_factory: sessionmaker[Session],
    clean_users_table: None,
) -> None:
    client = _create_pg_client(pg_session_factory)

    # Scenario 2: Duplicate CLI create fails and leaves 1 row.
    first = _run_cli_subprocess(
        [
            "--email",
            "dup-admin@example.edu",
            "--first-name",
            "First",
            "--last-name",
            "Admin",
            "--password-stdin",
        ],
        stdin_text="DuplicateAdminPassword15!\n",
    )
    assert first.returncode == 0, first.stderr

    second = _run_cli_subprocess(
        [
            "--email",
            "DUP-ADMIN@example.edu",
            "--first-name",
            "Second",
            "--last-name",
            "Admin",
            "--password-stdin",
        ],
        stdin_text="AnotherAdminPassword15!\n",
    )
    assert second.returncode != 0
    with migrated_pg_engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM users WHERE email = 'dup-admin@example.edu'")
        ).scalar_one()
        assert count == 1

    # Scenario 3: Active student promoted via --promote-existing --yes keeps original password.
    reg_active = client.post(
        "/api/v1/auth/register",
        json={
            "email": "promote-me@example.edu",
            "password": "OriginalStudentPass15!",
            "first_name": "Grace",
            "last_name": "Hopper",
        },
    )
    assert reg_active.status_code == 201

    promote_cli = _run_cli_subprocess(
        ["--email", "promote-me@example.edu", "--promote-existing", "--yes"],
    )
    assert promote_cli.returncode == 0, promote_cli.stderr

    login_after_promote = client.post(
        "/api/v1/auth/login",
        json={
            "email": "promote-me@example.edu",
            "password": "OriginalStudentPass15!",
        },
    )
    assert login_after_promote.status_code == 200
    promoted_token = login_after_promote.json()["access_token"]
    assert (
        client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {promoted_token}"},
        ).status_code
        == 200
    )

    # Scenario 4: Inactive student cannot be promoted via --promote-existing --yes.
    reg_inactive = client.post(
        "/api/v1/auth/register",
        json={
            "email": "inactive-stud@example.edu",
            "password": "InactiveStudentPass15!",
            "first_name": "Alan",
            "last_name": "Turing",
        },
    )
    assert reg_inactive.status_code == 201
    inactive_id = reg_inactive.json()["id"]

    deact = client.patch(
        f"/api/v1/admin/users/{inactive_id}/status",
        headers={"Authorization": f"Bearer {promoted_token}"},
        json={"is_active": False},
    )
    assert deact.status_code == 200

    promote_inactive = _run_cli_subprocess(
        ["--email", "inactive-stud@example.edu", "--promote-existing", "--yes"],
    )
    assert promote_inactive.returncode != 0

    with migrated_pg_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT role, is_active FROM users WHERE email = 'inactive-stud@example.edu'"
            )
        ).fetchone()
        assert row == ("student", False)


def test_cli_promote_existing_toctou_deactivation_during_confirmation_on_postgres(
    migrated_pg_engine: Engine,
    pg_session_factory: sessionmaker[Session],
    clean_users_table: None,
) -> None:
    """User deactivated on another PG connection during CLI confirmation is NOT promoted."""
    import io

    from app.authorization.roles import Role
    from app.cli.create_admin import build_parser, run_create_admin
    from app.core.security.passwords import PasswordPolicy
    from app.repositories.user_repository import SqlAlchemyUserRepository

    setup_session = pg_session_factory()
    try:
        setup_repo = SqlAlchemyUserRepository(setup_session)
        student = setup_repo.create(
            email="toctou-cli@example.edu",
            hashed_password="h",
            first_name="Toctou",
            last_name="Student",
            role=Role.STUDENT,
            is_active=True,
        )
    finally:
        setup_session.close()

    def _deactivate_from_other_connection(_prompt: str) -> str:
        other_session = pg_session_factory()
        try:
            other_repo = SqlAlchemyUserRepository(other_session)
            other_repo.update_status_with_last_admin_guard(student.id, False)
        finally:
            other_session.close()
        return "toctou-cli@example.edu"

    cli_session = pg_session_factory()
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        args = build_parser().parse_args(
            ["--email", "toctou-cli@example.edu", "--promote-existing"]
        )
        code = run_create_admin(
            args,
            user_repository=SqlAlchemyUserRepository(cli_session),
            password_hasher=Argon2PasswordHasher(
                time_cost=2, memory_cost=19456, parallelism=1
            ),
            password_policy=PasswordPolicy(),
            confirm_fn=_deactivate_from_other_connection,
            stdout=stdout,
            stderr=stderr,
        )
    finally:
        cli_session.close()

    assert code != 0
    assert "inactive" in stderr.getvalue().lower()
    with migrated_pg_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT role, is_active FROM users WHERE email = 'toctou-cli@example.edu'"
            )
        ).fetchone()
        assert row == ("student", False)


def test_argon2_needs_rehash_persists_updated_hash_in_postgres(
    migrated_pg_engine: Engine,
    pg_session_factory: sessionmaker[Session],
    clean_users_table: None,
) -> None:
    """Logging in with upgraded Argon2id parameters persists the rehashed value in PG."""
    from app.authorization.roles import Role
    from app.core.security.passwords import PasswordPolicy
    from app.repositories.user_repository import SqlAlchemyUserRepository
    from app.services.auth_service import AuthService

    old_hasher = Argon2PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
    upgraded_hasher = Argon2PasswordHasher(time_cost=3, memory_cost=19456, parallelism=1)
    raw_password = "RehashPostgresPassword15!"
    old_hash = old_hasher.hash(raw_password)
    assert "t=2," in old_hash

    setup_session = pg_session_factory()
    try:
        SqlAlchemyUserRepository(setup_session).create(
            email="rehash@example.edu",
            hashed_password=old_hash,
            first_name="Rehash",
            last_name="User",
            role=Role.STUDENT,
            is_active=True,
        )
    finally:
        setup_session.close()

    login_session = pg_session_factory()
    try:
        service = AuthService(
            user_repository=SqlAlchemyUserRepository(login_session),
            password_hasher=upgraded_hasher,
            password_policy=PasswordPolicy(),
            token_service=JwtTokenService(secret_key=TEST_JWT_SECRET),
            rate_limiter=InMemoryLoginRateLimiter(),
        )
        token_result = service.login(
            email="rehash@example.edu",
            password=raw_password,
            client_ip="127.0.0.1",
        )
        assert token_result.access_token
    finally:
        login_session.close()

    with migrated_pg_engine.connect() as conn:
        stored_hash = conn.execute(
            text("SELECT hashed_password FROM users WHERE email = 'rehash@example.edu'")
        ).scalar_one()

    assert stored_hash != old_hash
    assert "t=3," in stored_hash
    assert upgraded_hasher.verify(raw_password, stored_hash) is True
    assert upgraded_hasher.needs_rehash(stored_hash) is False
