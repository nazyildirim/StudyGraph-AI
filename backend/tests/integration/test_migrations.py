"""PostgreSQL Alembic migration upgrade/downgrade, drift, and constraint tests."""

from __future__ import annotations

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.postgres


def test_alembic_upgrade_downgrade_reupgrade_and_drift_check(
    pg_engine: Engine,
    verified_alembic_config: Config,
) -> None:
    cfg = verified_alembic_config

    # Start from a clean base schema.
    command.downgrade(cfg, "base")
    with pg_engine.connect() as conn:
        assert "users" not in inspect(conn).get_table_names(schema="public")

    # Upgrade to head and inspect schema details.
    command.upgrade(cfg, "head")
    with pg_engine.connect() as conn:
        inspector = inspect(conn)
        assert "users" in inspector.get_table_names(schema="public")

        columns = {col["name"]: col for col in inspector.get_columns("users")}
        assert set(columns.keys()) == {
            "id",
            "email",
            "hashed_password",
            "first_name",
            "last_name",
            "role",
            "is_active",
            "created_at",
            "updated_at",
        }
        assert "nextval" in str(columns["id"].get("default", ""))
        assert columns["created_at"]["type"].timezone is True
        assert columns["updated_at"]["type"].timezone is True

        pk = inspector.get_pk_constraint("users")
        assert pk["name"] == "pk_users"
        assert pk["constrained_columns"] == ["id"]

        unique_names = {c["name"] for c in inspector.get_unique_constraints("users")}
        assert "uq_users_email" in unique_names

        check_names = {c["name"] for c in inspector.get_check_constraints("users")}
        assert {"ck_users_role", "ck_users_email_lowercase"} <= check_names

        index_names = {idx["name"] for idx in inspector.get_indexes("users")}
        assert "ix_users_role" in index_names

    # Verify zero drift between SQLAlchemy ORM metadata and Alembic migrations.
    command.check(cfg)

    # Verify downgrade cleanly drops table and re-upgrade restores it.
    command.downgrade(cfg, "base")
    with pg_engine.connect() as conn:
        assert "users" not in inspect(conn).get_table_names(schema="public")

    command.upgrade(cfg, "head")
    with pg_engine.connect() as conn:
        assert "users" in inspect(conn).get_table_names(schema="public")


def test_db_constraints_reject_uppercase_email_invalid_role_and_duplicate_email(
    migrated_pg_engine: Engine,
    clean_users_table: None,
) -> None:
    # Uppercase email rejected by ck_users_email_lowercase
    with pytest.raises(IntegrityError):
        with migrated_pg_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (email, hashed_password, first_name, last_name, role) "
                    "VALUES ('Upper@Example.Edu', 'hash', 'A', 'B', 'student')"
                )
            )

    # Invalid role rejected by ck_users_role
    with pytest.raises(IntegrityError):
        with migrated_pg_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (email, hashed_password, first_name, last_name, role) "
                    "VALUES ('valid@example.edu', 'hash', 'A', 'B', 'superadmin')"
                )
            )

    # Valid insert followed by duplicate email rejected by uq_users_email
    with migrated_pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (email, hashed_password, first_name, last_name, role) "
                "VALUES ('dup@example.edu', 'hash', 'A', 'B', 'student')"
            )
        )

    with pytest.raises(IntegrityError):
        with migrated_pg_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (email, hashed_password, first_name, last_name, role) "
                    "VALUES ('dup@example.edu', 'hash2', 'C', 'D', 'student')"
                )
            )
