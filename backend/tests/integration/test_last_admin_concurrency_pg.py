"""Real PostgreSQL concurrency tests for the last-active-admin invariant.

Tests use separate PostgreSQL connections synchronized via `threading.Barrier`
with explicit `lock_timeout` to verify:
1. Mutual deactivation between 2 active admins (20 iterations) -> exactly 1 active admin.
2. Mixed demote + deactivate between 2 active admins (20 iterations) -> >= 1 active admin.
3. Sole admin self-deactivation racing with student promotion (20 iterations) -> >= 1 active admin.
4. Zero deadlocks or lock timeouts across all runs.
5. Isolated test-only negative control proving that an unlocked implementation
   violates the invariant under the same race condition.
"""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.authorization.roles import Role
from app.repositories.user_repository import (
    LastActiveAdminError,
    SqlAlchemyUserRepository,
)

pytestmark = pytest.mark.postgres
ITERATIONS = 20


def _count_active_admins(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT count(*) FROM users "
                    "WHERE role = 'admin' AND is_active IS TRUE"
                )
            ).scalar_one()
        )


def _configure_lock_timeout(session: Session) -> None:
    session.execute(text("SET lock_timeout = '5s'"))


def test_mutual_admin_deactivation_concurrency_20_iterations(
    migrated_pg_engine: Engine,
    pg_session_factory: sessionmaker[Session],
    clean_users_table: None,
) -> None:
    for iteration in range(ITERATIONS):
        with migrated_pg_engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))

        setup = pg_session_factory()
        try:
            setup_repo = SqlAlchemyUserRepository(setup)
            admin_a = setup_repo.create(
                email=f"a{iteration}@example.edu",
                hashed_password="h",
                first_name="Admin",
                last_name="A",
                role=Role.ADMIN,
            )
            admin_b = setup_repo.create(
                email=f"b{iteration}@example.edu",
                hashed_password="h",
                first_name="Admin",
                last_name="B",
                role=Role.ADMIN,
            )
        finally:
            setup.close()

        barrier = threading.Barrier(2)
        outcomes: list[str] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def deactivate_worker(target_id: int) -> None:
            session = pg_session_factory()
            try:
                _configure_lock_timeout(session)
                repo = SqlAlchemyUserRepository(session)
                barrier.wait()
                try:
                    repo.update_status_with_last_admin_guard(target_id, False)
                    with lock:
                        outcomes.append("ok")
                except LastActiveAdminError:
                    with lock:
                        outcomes.append("conflict")
            except Exception as exc:
                with lock:
                    errors.append(exc)
            finally:
                session.close()

        t1 = threading.Thread(target=deactivate_worker, args=(admin_b.id,))
        t2 = threading.Thread(target=deactivate_worker, args=(admin_a.id,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert errors == [], f"Unexpected DB/deadlock errors: {errors}"
        assert sorted(outcomes) == ["conflict", "ok"]
        assert _count_active_admins(migrated_pg_engine) == 1


def test_mixed_demote_and_deactivate_concurrency_20_iterations(
    migrated_pg_engine: Engine,
    pg_session_factory: sessionmaker[Session],
    clean_users_table: None,
) -> None:
    for iteration in range(ITERATIONS):
        with migrated_pg_engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))

        setup = pg_session_factory()
        try:
            setup_repo = SqlAlchemyUserRepository(setup)
            admin_a = setup_repo.create(
                email=f"ma{iteration}@example.edu",
                hashed_password="h",
                first_name="Admin",
                last_name="A",
                role=Role.ADMIN,
            )
            admin_b = setup_repo.create(
                email=f"mb{iteration}@example.edu",
                hashed_password="h",
                first_name="Admin",
                last_name="B",
                role=Role.ADMIN,
            )
        finally:
            setup.close()

        barrier = threading.Barrier(2)
        outcomes: list[str] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def demote_b() -> None:
            session = pg_session_factory()
            try:
                _configure_lock_timeout(session)
                repo = SqlAlchemyUserRepository(session)
                barrier.wait()
                try:
                    repo.update_role_with_last_admin_guard(admin_b.id, Role.STUDENT)
                    with lock:
                        outcomes.append("ok")
                except LastActiveAdminError:
                    with lock:
                        outcomes.append("conflict")
            except Exception as exc:
                with lock:
                    errors.append(exc)
            finally:
                session.close()

        def deactivate_a() -> None:
            session = pg_session_factory()
            try:
                _configure_lock_timeout(session)
                repo = SqlAlchemyUserRepository(session)
                barrier.wait()
                try:
                    repo.update_status_with_last_admin_guard(admin_a.id, False)
                    with lock:
                        outcomes.append("ok")
                except LastActiveAdminError:
                    with lock:
                        outcomes.append("conflict")
            except Exception as exc:
                with lock:
                    errors.append(exc)
            finally:
                session.close()

        t1 = threading.Thread(target=demote_b)
        t2 = threading.Thread(target=deactivate_a)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert errors == [], f"Unexpected DB/deadlock errors: {errors}"
        assert sorted(outcomes) == ["conflict", "ok"]
        assert _count_active_admins(migrated_pg_engine) == 1


def test_sole_admin_deactivate_racing_with_student_promotion_20_iterations(
    migrated_pg_engine: Engine,
    pg_session_factory: sessionmaker[Session],
    clean_users_table: None,
) -> None:
    for iteration in range(ITERATIONS):
        with migrated_pg_engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))

        setup = pg_session_factory()
        try:
            setup_repo = SqlAlchemyUserRepository(setup)
            sole_admin = setup_repo.create(
                email=f"sole{iteration}@example.edu",
                hashed_password="h",
                first_name="Sole",
                last_name="Admin",
                role=Role.ADMIN,
            )
            student = setup_repo.create(
                email=f"stud{iteration}@example.edu",
                hashed_password="h",
                first_name="Stud",
                last_name="One",
                role=Role.STUDENT,
            )
        finally:
            setup.close()

        barrier = threading.Barrier(2)
        errors: list[Exception] = []
        lock = threading.Lock()

        def deactivate_sole() -> None:
            session = pg_session_factory()
            try:
                _configure_lock_timeout(session)
                repo = SqlAlchemyUserRepository(session)
                barrier.wait()
                try:
                    repo.update_status_with_last_admin_guard(sole_admin.id, False)
                except LastActiveAdminError:
                    pass
            except Exception as exc:
                with lock:
                    errors.append(exc)
            finally:
                session.close()

        def promote_student() -> None:
            session = pg_session_factory()
            try:
                _configure_lock_timeout(session)
                repo = SqlAlchemyUserRepository(session)
                barrier.wait()
                repo.update_role_with_last_admin_guard(student.id, Role.ADMIN)
            except Exception as exc:
                with lock:
                    errors.append(exc)
            finally:
                session.close()

        t1 = threading.Thread(target=deactivate_sole)
        t2 = threading.Thread(target=promote_student)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert errors == [], f"Unexpected DB/deadlock errors: {errors}"
        assert _count_active_admins(migrated_pg_engine) >= 1


def test_negative_control_unlocked_deactivation_demonstrates_race_to_zero_admins(
    migrated_pg_engine: Engine,
    pg_session_factory: sessionmaker[Session],
    clean_users_table: None,
) -> None:
    """Isolated test-only negative control proving the race occurs without FOR UPDATE."""
    setup = pg_session_factory()
    try:
        repo = SqlAlchemyUserRepository(setup)
        admin_a = repo.create(
            email="neg-a@example.edu",
            hashed_password="h",
            first_name="Neg",
            last_name="A",
            role=Role.ADMIN,
        )
        admin_b = repo.create(
            email="neg-b@example.edu",
            hashed_password="h",
            first_name="Neg",
            last_name="B",
            role=Role.ADMIN,
        )
    finally:
        setup.close()

    read_barrier = threading.Barrier(2)

    def unlocked_deactivate(target_id: int) -> None:
        with migrated_pg_engine.begin() as conn:
            active_count = int(
                conn.execute(
                    text(
                        "SELECT count(*) FROM users "
                        "WHERE role = 'admin' AND is_active IS TRUE"
                    )
                ).scalar_one()
            )
            # Both connections read active_count == 2 before either writes.
            read_barrier.wait()
            if active_count > 1:
                conn.execute(
                    text("UPDATE users SET is_active = FALSE WHERE id = :uid"),
                    {"uid": target_id},
                )

    t1 = threading.Thread(target=unlocked_deactivate, args=(admin_a.id,))
    t2 = threading.Thread(target=unlocked_deactivate, args=(admin_b.id,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Without FOR UPDATE locking, the race leaves 0 active admins.
    assert _count_active_admins(migrated_pg_engine) == 0
