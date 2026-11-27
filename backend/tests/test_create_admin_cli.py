"""Unit tests for `python -m app.cli.create_admin` CLI utility."""

from __future__ import annotations

import io
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy.exc import OperationalError

from app.authorization.roles import Role
from app.cli.create_admin import build_parser, run_create_admin
from app.core.security.passwords import PasswordPolicy
from tests.fakes import FakePasswordHasher, FakeUserRepository

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _run_cli(
    argv: list[str],
    *,
    repo: FakeUserRepository,
    hasher: FakePasswordHasher | None = None,
    passwords: list[str] | None = None,
    stdin_text: str = "",
    confirm_response: str = "",
) -> tuple[int, str, str]:
    parser = build_parser()
    args = parser.parse_args(argv)
    prompt_iter = iter(passwords or [])
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = run_create_admin(
        args,
        user_repository=repo,
        password_hasher=hasher or FakePasswordHasher(),
        password_policy=PasswordPolicy(),
        getpass_fn=lambda _prompt: next(prompt_iter),
        confirm_fn=lambda _prompt: confirm_response,
        stdin=io.StringIO(stdin_text),
        stdout=stdout,
        stderr=stderr,
    )
    return code, stdout.getvalue(), stderr.getvalue()


def test_cli_rejects_password_as_command_line_argument() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(
            [
                "--email",
                "admin@example.edu",
                "--first-name",
                "Ada",
                "--last-name",
                "Lovelace",
                "--password",
                "NeverAllowCliPassword15!",
            ]
        )
    assert exc_info.value.code == 2


def test_create_admin_interactive_success_and_no_secret_output() -> None:
    repo = FakeUserRepository()
    hasher = FakePasswordHasher()
    secret_pw = "InteractiveAdminSecret15!"

    code, out, err = _run_cli(
        [
            "--email",
            "  Admin@Example.EDU ",
            "--first-name",
            " Ada ",
            "--last-name",
            " Lovelace ",
        ],
        repo=repo,
        hasher=hasher,
        passwords=[secret_pw, secret_pw],
    )

    assert code == 0
    assert err == ""
    assert "admin@example.edu" in out
    assert secret_pw not in out
    assert "fakehash$" not in out

    created = repo.get_by_email("admin@example.edu")
    assert created is not None
    assert created.role == Role.ADMIN.value
    assert created.is_active is True
    assert created.first_name == "Ada"
    assert created.last_name == "Lovelace"
    assert hasher.verify(secret_pw, created.hashed_password) is True


def test_create_admin_password_stdin_preserves_spaces_and_strips_newline() -> None:
    repo = FakeUserRepository()
    hasher = FakePasswordHasher()
    padded_pw = "  stdin-secret-password-15  "

    code, out, err = _run_cli(
        [
            "--email",
            "ci-admin@example.edu",
            "--first-name",
            "CI",
            "--last-name",
            "Admin",
            "--password-stdin",
        ],
        repo=repo,
        hasher=hasher,
        stdin_text=f"{padded_pw}\n",
    )

    assert code == 0
    assert err == ""
    assert padded_pw not in out

    created = repo.get_by_email("ci-admin@example.edu")
    assert created is not None
    assert hasher.verify(padded_pw, created.hashed_password) is True
    assert hasher.verify(padded_pw.strip(), created.hashed_password) is False


def test_create_admin_rejects_mismatch_and_invalid_password() -> None:
    repo = FakeUserRepository()

    # Mismatched getpass entries
    code1, _out1, err1 = _run_cli(
        [
            "--email",
            "a1@example.edu",
            "--first-name",
            "A",
            "--last-name",
            "One",
        ],
        repo=repo,
        passwords=["ValidPasswordFifteen15!", "DifferentPassword15!"],
    )
    assert code1 != 0
    assert "do not match" in err1.lower()
    assert "ValidPasswordFifteen15!" not in err1
    assert repo.get_by_email("a1@example.edu") is None

    # Short password rejected by PasswordPolicy
    code2, _out2, err2 = _run_cli(
        [
            "--email",
            "a2@example.edu",
            "--first-name",
            "A",
            "--last-name",
            "Two",
            "--password-stdin",
        ],
        repo=repo,
        stdin_text="TooShort123\n",
    )
    assert code2 != 0
    assert "TooShort123" not in err2
    assert repo.get_by_email("a2@example.edu") is None


def test_create_admin_rejects_duplicate_email_without_promote_flag() -> None:
    repo = FakeUserRepository()
    existing = repo.create(
        email="student@example.edu",
        hashed_password="original-student-hash",
        first_name="Student",
        last_name="One",
        role=Role.STUDENT,
        is_active=True,
    )

    code, _out, err = _run_cli(
        [
            "--email",
            "STUDENT@example.edu",
            "--first-name",
            "Other",
            "--last-name",
            "Name",
            "--password-stdin",
        ],
        repo=repo,
        stdin_text="ValidPasswordFifteen15!\n",
    )

    assert code != 0
    assert "--promote-existing" in err
    assert existing.role == Role.STUDENT.value
    assert existing.hashed_password == "original-student-hash"
    assert existing.is_active is True


def test_promote_existing_requires_explicit_confirmation_and_preserves_password_and_status() -> None:
    repo = FakeUserRepository()
    student = repo.create(
        email="student@example.edu",
        hashed_password="original-student-hash",
        first_name="Student",
        last_name="One",
        role=Role.STUDENT,
        is_active=True,
    )

    # Wrong confirmation -> aborted, no mutation
    code_abort, _out_a, err_a = _run_cli(
        ["--email", "student@example.edu", "--promote-existing"],
        repo=repo,
        confirm_response="wrong@example.edu",
    )
    assert code_abort != 0
    assert "aborted" in err_a.lower()
    assert student.role == Role.STUDENT.value

    # Exact email confirmation -> promoted, password and active status untouched
    code_ok, out_ok, err_ok = _run_cli(
        ["--email", "STUDENT@example.edu", "--promote-existing"],
        repo=repo,
        confirm_response="student@example.edu",
    )
    assert code_ok == 0
    assert err_ok == ""
    assert "role=admin" in out_ok
    assert student.role == Role.ADMIN.value
    assert student.hashed_password == "original-student-hash"
    assert student.is_active is True


def test_promote_existing_rejects_inactive_missing_already_admin_and_password_stdin() -> None:
    repo = FakeUserRepository()
    inactive = repo.create(
        email="inactive@example.edu",
        hashed_password="h",
        first_name="In",
        last_name="Active",
        role=Role.STUDENT,
        is_active=False,
    )
    already_admin = repo.create(
        email="admin@example.edu",
        hashed_password="h",
        first_name="Ad",
        last_name="Min",
        role=Role.ADMIN,
        is_active=True,
    )

    # Inactive user cannot be promoted or reactivated
    code_inact, _o, _e = _run_cli(
        ["--email", "inactive@example.edu", "--promote-existing", "--yes"],
        repo=repo,
    )
    assert code_inact != 0
    assert inactive.role == Role.STUDENT.value
    assert inactive.is_active is False

    # Missing user
    code_miss, _o, _e = _run_cli(
        ["--email", "missing@example.edu", "--promote-existing", "--yes"],
        repo=repo,
    )
    assert code_miss != 0

    # Already active admin
    code_dup, _o, _e = _run_cli(
        ["--email", "admin@example.edu", "--promote-existing", "--yes"],
        repo=repo,
    )
    assert code_dup != 0
    assert already_admin.role == Role.ADMIN.value

    # Combining --promote-existing and --password-stdin is rejected
    code_combo, _o, _e = _run_cli(
        [
            "--email",
            "inactive@example.edu",
            "--promote-existing",
            "--password-stdin",
            "--yes",
        ],
        repo=repo,
        stdin_text="ValidPasswordFifteen15!\n",
    )
    assert code_combo != 0


def test_promote_existing_blocks_promotion_if_deactivated_during_confirmation() -> None:
    repo = FakeUserRepository()
    student = repo.create(
        email="race-student@example.edu",
        hashed_password="original-hash",
        first_name="Race",
        last_name="Student",
        role=Role.STUDENT,
        is_active=True,
    )

    def _deactivate_then_confirm(_prompt: str) -> str:
        student.is_active = False
        return "race-student@example.edu"

    parser = build_parser()
    args = parser.parse_args(
        ["--email", "race-student@example.edu", "--promote-existing"]
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = run_create_admin(
        args,
        user_repository=repo,
        password_hasher=FakePasswordHasher(),
        password_policy=PasswordPolicy(),
        confirm_fn=_deactivate_then_confirm,
        stdout=stdout,
        stderr=stderr,
    )

    assert code != 0
    assert "inactive" in stderr.getvalue().lower()
    assert student.role == Role.STUDENT.value
    assert student.is_active is False


def test_db_failure_does_not_leak_connection_string_or_password() -> None:
    class _FailingRepo(FakeUserRepository):
        def create(self, **kwargs: object) -> object:
            raise OperationalError(
                "INSERT",
                {},
                Exception(
                    "connection failed: postgresql+psycopg://u:TopSecretDbPass@127.0.0.1:5432/db"
                ),
            )

    repo = _FailingRepo()
    code, out, err = _run_cli(
        [
            "--email",
            "admin@example.edu",
            "--first-name",
            "Ada",
            "--last-name",
            "Lovelace",
            "--password-stdin",
        ],
        repo=repo,
        stdin_text="ValidAdminPassword15!\n",
    )

    assert code != 0
    assert "TopSecretDbPass" not in out
    assert "TopSecretDbPass" not in err
    assert "ValidAdminPassword15!" not in out
    assert "ValidAdminPassword15!" not in err
    assert "rolled back" in err.lower()


def test_cli_module_imports_cleanly_without_env_or_db(tmp_path: Path) -> None:
    clean_env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(BACKEND_DIR),
    }
    script = (
        "import app.cli.create_admin\n"
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
