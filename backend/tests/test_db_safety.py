"""Unit tests for the destructive-test database safety guard (G2-G8)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.integration.db_safety import (
    ALLOW_FLAG_ENV,
    UnsafeTestDatabaseError,
    assert_connected_database_is_safe,
    assert_safe_test_database,
)

VALID_URL = "postgresql+psycopg://studygraph_test:SuperSecret99@127.0.0.1:5433/studygraph_test"
VALID_ENV = {
    ALLOW_FLAG_ENV: "1",
    "DATABASE_URL": "postgresql+psycopg://studygraph:DevSecret@127.0.0.1:5432/studygraph_db",
}


def test_valid_test_database_passes() -> None:
    parsed = assert_safe_test_database(VALID_URL, VALID_ENV)
    assert parsed.drivername == "postgresql+psycopg"
    assert parsed.host == "127.0.0.1"
    assert parsed.port == 5433
    assert parsed.database == "studygraph_test"


def test_g2_requires_explicit_allow_flag() -> None:
    with pytest.raises(UnsafeTestDatabaseError) as exc_info:
        assert_safe_test_database(VALID_URL, {})
    assert "SuperSecret99" not in str(exc_info.value)


def test_g3_requires_psycopg3_driver() -> None:
    bad_driver = "postgresql+psycopg2://u:SuperSecret99@127.0.0.1:5433/studygraph_test"
    with pytest.raises(UnsafeTestDatabaseError) as exc_info:
        assert_safe_test_database(bad_driver, VALID_ENV)
    assert "SuperSecret99" not in str(exc_info.value)


@pytest.mark.parametrize(
    "bad_url",
    [
        "postgresql+psycopg://u:SuperSecret99@192.168.1.10:5433/studygraph_test",
        "postgresql+psycopg://u:SuperSecret99@db.example.com:5433/studygraph_test",
        "postgresql+psycopg://u:SuperSecret99@127.0.0.1:5432/studygraph_test",
        "postgresql+psycopg://u:SuperSecret99@127.0.0.1/studygraph_test",
    ],
)
def test_g4_requires_localhost_and_port_5433(bad_url: str) -> None:
    with pytest.raises(UnsafeTestDatabaseError) as exc_info:
        assert_safe_test_database(bad_url, VALID_ENV)
    assert "SuperSecret99" not in str(exc_info.value)


@pytest.mark.parametrize(
    "bad_url",
    [
        "postgresql+psycopg://u:SuperSecret99@127.0.0.1:5433/studygraph_db",
        "postgresql+psycopg://u:SuperSecret99@127.0.0.1:5433/postgres",
        "postgresql+psycopg://u:SuperSecret99@127.0.0.1:5433/",
    ],
)
def test_g5_requires_test_suffix(bad_url: str) -> None:
    with pytest.raises(UnsafeTestDatabaseError) as exc_info:
        assert_safe_test_database(bad_url, VALID_ENV)
    assert "SuperSecret99" not in str(exc_info.value)


def test_g6_rejects_same_target_as_dev_database_url_including_localhost_alias() -> None:
    env_same = {
        ALLOW_FLAG_ENV: "1",
        "DATABASE_URL": "postgresql+psycopg://other:OtherPass@localhost:5433/studygraph_test",
    }
    with pytest.raises(UnsafeTestDatabaseError) as exc_info:
        assert_safe_test_database(VALID_URL, env_same)
    assert "SuperSecret99" not in str(exc_info.value)
    assert "OtherPass" not in str(exc_info.value)


def test_g7_and_g8_live_connection_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = MagicMock()
    conn.execute.return_value.scalar_one.return_value = "studygraph_test"

    fake_inspector = MagicMock()
    fake_inspector.get_table_names.return_value = ["alembic_version", "users"]
    monkeypatch.setattr(
        "tests.integration.db_safety.inspect",
        lambda _connection: fake_inspector,
    )

    assert_connected_database_is_safe(conn)


def test_g7_rejects_live_database_without_test_suffix() -> None:
    conn = MagicMock()
    conn.execute.return_value.scalar_one.return_value = "studygraph_db"

    with pytest.raises(UnsafeTestDatabaseError):
        assert_connected_database_is_safe(conn)


def test_g8_rejects_unexpected_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = MagicMock()
    conn.execute.return_value.scalar_one.return_value = "studygraph_test"

    fake_inspector = MagicMock()
    fake_inspector.get_table_names.return_value = ["alembic_version", "users", "courses"]
    monkeypatch.setattr(
        "tests.integration.db_safety.inspect",
        lambda _connection: fake_inspector,
    )

    with pytest.raises(UnsafeTestDatabaseError) as exc_info:
        assert_connected_database_is_safe(conn)
    assert "courses" in str(exc_info.value)
