"""Unit tests for User ORM metadata, Role enum, and offline Alembic setup."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, UniqueConstraint

from app.authorization.roles import Role
from app.models import Base, User

BACKEND_DIR = Path(__file__).resolve().parent.parent


def test_role_enum_values_match_database_design() -> None:
    assert [role.value for role in Role] == ["student", "instructor", "admin"]


def test_user_model_columns_and_constraints() -> None:
    table = Base.metadata.tables["users"]
    assert User.__tablename__ == "users"

    expected_columns = {
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
    assert set(table.columns.keys()) == expected_columns
    assert table.c.id.primary_key is True
    assert table.c.email.type.length == 255
    assert table.c.hashed_password.type.length == 255
    assert table.c.first_name.type.length == 100
    assert table.c.last_name.type.length == 100
    assert table.c.role.type.length == 20
    assert table.c.created_at.type.timezone is True
    assert table.c.updated_at.type.timezone is True

    for col_name in expected_columns:
        assert table.c[col_name].nullable is False

    assert table.primary_key.name == "pk_users"

    unique_names = {
        c.name for c in table.constraints if isinstance(c, UniqueConstraint)
    }
    assert "uq_users_email" in unique_names

    check_names = {
        c.name for c in table.constraints if isinstance(c, CheckConstraint)
    }
    assert {"ck_users_role", "ck_users_email_lowercase"} <= check_names

    index_names = {idx.name for idx in table.indexes}
    assert "ix_users_role" in index_names


def test_alembic_script_directory_loads_without_db() -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    assert not cfg.get_main_option("sqlalchemy.url")

    script_dir = ScriptDirectory.from_config(cfg)
    heads = script_dir.get_heads()
    # Later migrations (courses, RAG) extend the chain; the users migration must
    # stay the base revision and the history must remain linear.
    assert len(heads) == 1
    assert script_dir.get_revision("0001_create_users").down_revision is None
