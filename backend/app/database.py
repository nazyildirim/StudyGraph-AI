"""Lazy SQLAlchemy 2.0 database engine and session management.

No engine or connection pool is created on module import so that existing
stateless endpoints and unit tests run without PostgreSQL or .env files.
"""

from __future__ import annotations

from collections.abc import Generator
import threading

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_lock = threading.Lock()
_engine: Engine | None = None
_engine_url: str | None = None
_session_factory: sessionmaker[Session] | None = None


def create_db_engine(database_url: str) -> Engine:
    """Create a configured SQLAlchemy 2.0 synchronous engine."""
    return create_engine(
        database_url,
        pool_pre_ping=True,
        future=True,
    )


def get_engine() -> Engine:
    """Return the lazily initialized Engine for the current DATABASE_URL."""
    global _engine, _engine_url, _session_factory

    database_url = get_settings().require_database_url()
    with _lock:
        if _engine is None or _engine_url != database_url:
            if _engine is not None:
                _engine.dispose()
            _engine = create_db_engine(database_url)
            _engine_url = database_url
            _session_factory = sessionmaker(
                bind=_engine,
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
                class_=Session,
            )
        return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the lazily initialized sessionmaker."""
    get_engine()
    if _session_factory is None:
        raise RuntimeError("Database session factory is not initialized.")
    return _session_factory


def reset_db_state() -> None:
    """Dispose the cached engine and reset module state (for tests)."""
    global _engine, _engine_url, _session_factory

    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _engine_url = None
        _session_factory = None


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a database session per request."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
