"""PostgreSQL concurrency tests for duplicate email registration (`uq_users_email`)."""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.security.passwords import Argon2PasswordHasher, PasswordPolicy
from app.core.security.rate_limit import InMemoryLoginRateLimiter
from app.core.security.tokens import JwtTokenService
from app.repositories.user_repository import (
    EmailAlreadyRegisteredError,
    SqlAlchemyUserRepository,
)
from app.services.auth_service import AuthService

pytestmark = pytest.mark.postgres
TEST_JWT_SECRET = "I" * 48


def test_concurrent_duplicate_email_registration_20_iterations(
    migrated_pg_engine: Engine,
    pg_session_factory: sessionmaker[Session],
    clean_users_table: None,
) -> None:
    """Two concurrent connections registering the same email: 1 succeeds, 1 gets 409."""
    hasher = Argon2PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
    policy = PasswordPolicy()
    token_service = JwtTokenService(secret_key=TEST_JWT_SECRET)
    rate_limiter = InMemoryLoginRateLimiter()

    for iteration in range(20):
        email = f"concurrent{iteration}@example.edu"
        barrier = threading.Barrier(2)
        outcomes: list[str] = []
        outcomes_lock = threading.Lock()

        def worker(email_addr: str = email, b: threading.Barrier = barrier) -> None:
            session = pg_session_factory()
            try:
                repo = SqlAlchemyUserRepository(session)
                service = AuthService(
                    user_repository=repo,
                    password_hasher=hasher,
                    password_policy=policy,
                    token_service=token_service,
                    rate_limiter=rate_limiter,
                )
                b.wait()
                try:
                    service.register(
                        email=email_addr,
                        password="ConcurrentValidPassword15!",
                        first_name="Ada",
                        last_name="Lovelace",
                    )
                    with outcomes_lock:
                        outcomes.append("created")
                except EmailAlreadyRegisteredError:
                    with outcomes_lock:
                        outcomes.append("conflict")
            finally:
                session.close()

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert sorted(outcomes) == ["conflict", "created"]

        with migrated_pg_engine.connect() as conn:
            count = conn.execute(
                text("SELECT count(*) FROM users WHERE email = :email"),
                {"email": email},
            ).scalar_one()
            assert count == 1
