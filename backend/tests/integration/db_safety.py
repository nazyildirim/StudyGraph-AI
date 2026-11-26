"""Multi-layer safety guard preventing destructive integration tests on dev DBs.

Rules enforced before any DDL/TRUNCATE runs:
- G2: STUDYGRAPH_ALLOW_DESTRUCTIVE_DB_TESTS=1 must be explicitly set.
- G3: Driver must be `postgresql+psycopg`.
- G4: Host must be `127.0.0.1` or `localhost`, and port must be `5433`.
- G5: Database name must end with `_test`.
- G6: TEST_DATABASE_URL must not target the same host/port/db as DATABASE_URL.
- G7: Live `SELECT current_database()` must end with `_test`.
- G8: Public schema must contain no unexpected tables outside `allowed_tables`.
"""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, URL, make_url

EXPECTED_DRIVER = "postgresql+psycopg"
ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost"})
EXPECTED_TEST_PORT = 5433
REQUIRED_DB_SUFFIX = "_test"
ALLOW_FLAG_ENV = "STUDYGRAPH_ALLOW_DESTRUCTIVE_DB_TESTS"
DEFAULT_ALLOWED_TABLES = frozenset({"alembic_version", "users"})


class UnsafeTestDatabaseError(RuntimeError):
    """Raised when TEST_DATABASE_URL fails destructive-test safety checks."""


def _mask_url(url: URL) -> str:
    return url.render_as_string(hide_password=True)


def _normalize_target(url: URL) -> tuple[str, int, str]:
    host = (url.host or "").strip().lower()
    if host == "localhost":
        host = "127.0.0.1"
    port = url.port if url.port is not None else 5432
    database = (url.database or "").strip()
    return (host, port, database)


def assert_safe_test_database(
    test_database_url: str,
    env: Mapping[str, str],
) -> URL:
    """Validate TEST_DATABASE_URL and environment flags without connecting."""
    if not test_database_url or not test_database_url.strip():
        raise UnsafeTestDatabaseError("TEST_DATABASE_URL bos olamaz.")

    try:
        parsed = make_url(test_database_url.strip())
    except Exception as error:
        raise UnsafeTestDatabaseError(
            "TEST_DATABASE_URL gecerli bir SQLAlchemy URL'si degil."
        ) from error

    masked = _mask_url(parsed)

    if env.get(ALLOW_FLAG_ENV) != "1":
        raise UnsafeTestDatabaseError(
            f"Yikici DB testleri icin {ALLOW_FLAG_ENV}=1 acikca ayarlanmalidir "
            f"(hedef: {masked})."
        )

    if parsed.drivername != EXPECTED_DRIVER:
        raise UnsafeTestDatabaseError(
            f"TEST_DATABASE_URL surucusu '{EXPECTED_DRIVER}' olmalidir "
            f"(bulunan: '{parsed.drivername}', hedef: {masked})."
        )

    host = (parsed.host or "").strip().lower()
    if host not in ALLOWED_HOSTS:
        raise UnsafeTestDatabaseError(
            f"TEST_DATABASE_URL yalnizca localhost/127.0.0.1 olabilir "
            f"(hedef: {masked})."
        )

    if parsed.port != EXPECTED_TEST_PORT:
        raise UnsafeTestDatabaseError(
            f"TEST_DATABASE_URL portu {EXPECTED_TEST_PORT} olmalidir "
            f"(hedef: {masked})."
        )

    database = (parsed.database or "").strip()
    if not database or not database.endswith(REQUIRED_DB_SUFFIX):
        raise UnsafeTestDatabaseError(
            f"Test veritabani adi '{REQUIRED_DB_SUFFIX}' ile bitmelidir "
            f"(hedef: {masked})."
        )

    dev_url_raw = env.get("DATABASE_URL", "").strip()
    if dev_url_raw:
        try:
            dev_parsed = make_url(dev_url_raw)
        except Exception:
            dev_parsed = None
        if dev_parsed is not None and _normalize_target(parsed) == _normalize_target(
            dev_parsed
        ):
            raise UnsafeTestDatabaseError(
                "TEST_DATABASE_URL ile DATABASE_URL ayni hedefi gosteriyor; "
                f"gelistirme veritabani uzerinde test calistirilamaz (hedef: {masked})."
            )

    return parsed


def assert_connected_database_is_safe(
    connection: Connection,
    *,
    allowed_tables: frozenset[str] = DEFAULT_ALLOWED_TABLES,
) -> None:
    """Verify the live PostgreSQL connection targets an isolated test database."""
    current_db = connection.execute(text("SELECT current_database()")).scalar_one()
    if not isinstance(current_db, str) or not current_db.endswith(REQUIRED_DB_SUFFIX):
        raise UnsafeTestDatabaseError(
            f"Baglanilan veritabani '{current_db}' '{REQUIRED_DB_SUFFIX}' ile bitmiyor."
        )

    existing_tables = set(inspect(connection).get_table_names(schema="public"))
    unexpected_tables = sorted(existing_tables - set(allowed_tables))
    if unexpected_tables:
        raise UnsafeTestDatabaseError(
            "Test veritabaninda beklenmeyen tablolar bulundu; calisma durduruldu: "
            f"{', '.join(unexpected_tables)}"
        )
