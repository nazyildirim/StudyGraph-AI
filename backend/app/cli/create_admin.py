"""CLI utility to securely create or promote an administrator account.

Usage:
    python -m app.cli.create_admin --email admin@example.edu --first-name Ada --last-name Lovelace
    python -m app.cli.create_admin --email admin@example.edu --first-name Ada --last-name Lovelace --password-stdin
    python -m app.cli.create_admin --email existing@example.edu --promote-existing

Security guarantees:
- No default admin credentials, default passwords, or hardcoded secrets.
- Passwords are NEVER accepted as command-line arguments.
- Interactive mode uses `getpass` with double-entry confirmation.
- Automation mode supports `--password-stdin` (single line, whitespace preserved).
- `--promote-existing` requires explicit confirmation, never modifies password
  or `is_active`, and refuses inactive accounts.
- Passwords, hashes, and database URLs are never printed to stdout/stderr.
- Environment variables and database connections are loaded lazily only at
  execution time (never on module import).
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import getpass
import sys
from typing import TextIO

from sqlalchemy.exc import SQLAlchemyError

from app.authorization.roles import Role
from app.core.config import ConfigurationError, get_settings
from app.core.security.email import InvalidEmailError, normalize_email
from app.core.security.passwords import (
    Argon2PasswordHasher,
    PasswordHasher,
    PasswordPolicy,
    PasswordPolicyError,
)
from app.database import get_session_factory
from app.repositories.user_repository import (
    EmailAlreadyRegisteredError,
    InactiveUserError,
    SqlAlchemyUserRepository,
    UserNotFoundError,
    UserRepository,
)

MAX_NAME_LENGTH = 100


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser (intentionally omits any --password option)."""
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.create_admin",
        description=(
            "Create an initial admin account or explicitly promote an existing "
            "active user to admin."
        ),
    )
    parser.add_argument(
        "--email",
        required=True,
        help="Target admin email address.",
    )
    parser.add_argument(
        "--first-name",
        default=None,
        help="First name (required when creating a new admin account).",
    )
    parser.add_argument(
        "--last-name",
        default=None,
        help="Last name (required when creating a new admin account).",
    )
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read password as a single line from stdin (for non-interactive automation).",
    )
    parser.add_argument(
        "--promote-existing",
        action="store_true",
        help="Promote an existing active user to admin without changing password or status.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm --promote-existing non-interactively.",
    )
    return parser


def _validate_name(raw_value: str | None, field_label: str) -> str:
    if raw_value is None or not raw_value.strip():
        raise ValueError(f"{field_label} is required and cannot be blank.")
    cleaned = raw_value.strip()
    if len(cleaned) > MAX_NAME_LENGTH:
        raise ValueError(
            f"{field_label} must be at most {MAX_NAME_LENGTH} characters."
        )
    return cleaned


def _read_password(
    *,
    use_stdin: bool,
    stdin: TextIO,
    getpass_fn: Callable[[str], str],
) -> str:
    if use_stdin:
        line = stdin.readline()
        if not line:
            raise ValueError("No password provided on stdin.")
        return line.rstrip("\r\n")

    first = getpass_fn("Password (min 15 chars): ")
    second = getpass_fn("Confirm password: ")
    if first != second:
        raise ValueError("Passwords do not match.")
    return first


def run_create_admin(
    args: argparse.Namespace,
    *,
    user_repository: UserRepository,
    password_hasher: PasswordHasher,
    password_policy: PasswordPolicy,
    getpass_fn: Callable[[str], str] = getpass.getpass,
    confirm_fn: Callable[[str], str] = input,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Execute admin creation or promotion using injected dependencies."""
    try:
        normalized_email = normalize_email(args.email)
    except InvalidEmailError as error:
        print(f"Error: {error}", file=stderr)
        return 1

    if args.promote_existing:
        if args.password_stdin:
            print(
                "Error: --password-stdin cannot be combined with --promote-existing.",
                file=stderr,
            )
            return 1

        try:
            existing = user_repository.get_by_email(normalized_email)
        except SQLAlchemyError:
            print(
                "Error: Database lookup failed. No changes were committed.",
                file=stderr,
            )
            return 1

        if existing is None:
            print("Error: Target user does not exist.", file=stderr)
            return 1

        if not existing.is_active:
            print(
                "Error: Cannot promote an inactive user account.",
                file=stderr,
            )
            return 1

        if existing.role == Role.ADMIN.value:
            print("Error: User is already an active admin.", file=stderr)
            return 1

        if not args.yes:
            prompt = (
                f"Type '{normalized_email}' to confirm promoting this user to admin: "
            )
            confirmation = confirm_fn(prompt).strip().lower()
            if confirmation != normalized_email:
                print("Aborted: Confirmation did not match.", file=stderr)
                return 1

        try:
            promoted = user_repository.update_role_with_last_admin_guard(
                existing.id,
                Role.ADMIN,
                require_active=True,
            )
        except UserNotFoundError:
            print("Error: Target user does not exist.", file=stderr)
            return 1
        except InactiveUserError:
            print(
                "Error: Cannot promote an inactive user account.",
                file=stderr,
            )
            return 1
        except SQLAlchemyError:
            print(
                "Error: Database update failed. Transaction was rolled back.",
                file=stderr,
            )
            return 1

        print(
            f"Admin promotion succeeded: id={promoted.id}, "
            f"email={promoted.email}, role={promoted.role}",
            file=stdout,
        )
        return 0

    # New admin creation mode
    try:
        first_name = _validate_name(args.first_name, "first_name")
        last_name = _validate_name(args.last_name, "last_name")
    except ValueError as error:
        print(f"Error: {error}", file=stderr)
        return 1

    try:
        existing = user_repository.get_by_email(normalized_email)
    except SQLAlchemyError:
        print(
            "Error: Database lookup failed. No changes were committed.",
            file=stderr,
        )
        return 1

    if existing is not None:
        print(
            "Error: An account with this email already exists. "
            "Use --promote-existing to explicitly promote an active account.",
            file=stderr,
        )
        return 1

    try:
        raw_password = _read_password(
            use_stdin=args.password_stdin,
            stdin=stdin,
            getpass_fn=getpass_fn,
        )
        password_policy.validate(raw_password, email=normalized_email)
    except (ValueError, PasswordPolicyError) as error:
        print(f"Error: {error}", file=stderr)
        return 1

    hashed_password = password_hasher.hash(raw_password)
    try:
        created = user_repository.create(
            email=normalized_email,
            hashed_password=hashed_password,
            first_name=first_name,
            last_name=last_name,
            role=Role.ADMIN,
            is_active=True,
        )
    except EmailAlreadyRegisteredError:
        print(
            "Error: An account with this email already exists.",
            file=stderr,
        )
        return 1
    except SQLAlchemyError:
        print(
            "Error: Database write failed. Transaction was rolled back.",
            file=stderr,
        )
        return 1

    print(
        f"Admin user created: id={created.id}, "
        f"email={created.email}, role={created.role}",
        file=stdout,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point: lazily loads settings and database session only on run."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings = get_settings()
        settings.require_database_url()
        session_factory = get_session_factory()
        password_hasher = Argon2PasswordHasher(
            time_cost=settings.argon2_time_cost,
            memory_cost=settings.argon2_memory_cost,
            parallelism=settings.argon2_parallelism,
        )
    except ConfigurationError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 1

    session = session_factory()
    try:
        repository = SqlAlchemyUserRepository(session)
        return run_create_admin(
            args,
            user_repository=repository,
            password_hasher=password_hasher,
            password_policy=PasswordPolicy(),
        )
    except Exception:
        session.rollback()
        print(
            "Error: Unexpected failure. Transaction was rolled back.",
            file=sys.stderr,
        )
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
