"""Fixtures and safety guards for PostgreSQL integration tests."""

from __future__ import annotations

from collections.abc import Generator
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.database import create_db_engine
from tests.integration.db_safety import (
    UnsafeTestDatabaseError,
    assert_connected_database_is_safe,
    assert_safe_test_database,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_RAW_TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()

if not _RAW_TEST_DATABASE_URL:
    pytest.skip(
        "TEST_DATABASE_URL is not set; skipping PostgreSQL integration tests.",
        allow_module_level=True,
    )

try:
    _VERIFIED_TEST_URL = assert_safe_test_database(_RAW_TEST_DATABASE_URL, os.environ)
except UnsafeTestDatabaseError as error:
    pytest.exit(str(error), returncode=2)


def make_verified_alembic_config(verified_test_url: str) -> Config:
    """Create an Alembic Config strictly pinned to the verified test DB URL."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", verified_test_url)
    cfg.attributes["skip_logging_config"] = True
    return cfg


@pytest.fixture(scope="session")
def verified_alembic_config() -> Config:
    """Return an Alembic Config strictly pinned to the verified test DB URL."""
    return make_verified_alembic_config(
        _VERIFIED_TEST_URL.render_as_string(hide_password=False)
    )


@pytest.fixture(scope="session")
def pg_engine() -> Generator[Engine, None, None]:
    """Create a verified PostgreSQL engine after running live G7/G8 checks."""
    engine = create_db_engine(
        _VERIFIED_TEST_URL.render_as_string(hide_password=False)
    )
    try:
        with engine.connect() as connection:
            try:
                assert_connected_database_is_safe(connection)
            except UnsafeTestDatabaseError as error:
                pytest.exit(str(error), returncode=2)
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def migrated_pg_engine(
    pg_engine: Engine,
    verified_alembic_config: Config,
) -> Engine:
    """Ensure the verified test database is migrated to Alembic head."""
    command.upgrade(verified_alembic_config, "head")
    return pg_engine


@pytest.fixture(scope="session")
def pg_session_factory(migrated_pg_engine: Engine) -> sessionmaker[Session]:
    """Return a sessionmaker bound to the migrated PostgreSQL test engine."""
    return sessionmaker(
        bind=migrated_pg_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=Session,
    )


@pytest.fixture()
def clean_users_table(migrated_pg_engine: Engine) -> Generator[None, None, None]:
    """Truncate the `users` table before and after each integration test."""
    with migrated_pg_engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
    try:
        yield
    finally:
        with migrated_pg_engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))
