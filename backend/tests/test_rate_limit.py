"""Unit and concurrency tests for InMemoryLoginRateLimiter."""

from __future__ import annotations

import threading
import time

import pytest

from app.core.security.rate_limit import (
    InMemoryLoginRateLimiter,
    RateLimitExceededError,
)


class _FakeMonotonicClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_account_limit_blocks_after_threshold_and_resets_after_window() -> None:
    clock = _FakeMonotonicClock()
    limiter = InMemoryLoginRateLimiter(
        account_max_attempts=5,
        ip_max_attempts=30,
        window_seconds=900,
        clock=clock,
    )

    for _ in range(5):
        with limiter.acquire(client_ip="127.0.0.1", normalized_email="a@b.edu") as res:
            res.record_failure()

    with pytest.raises(RateLimitExceededError) as exc_info:
        limiter.acquire(client_ip="127.0.0.1", normalized_email="a@b.edu")
    assert exc_info.value.retry_after == 900

    clock.advance(901)
    with limiter.acquire(client_ip="127.0.0.1", normalized_email="a@b.edu") as res:
        res.record_success()


def test_success_clears_account_failures_and_exception_releases_slot() -> None:
    clock = _FakeMonotonicClock()
    limiter = InMemoryLoginRateLimiter(
        account_max_attempts=2,
        ip_max_attempts=10,
        window_seconds=60,
        clock=clock,
    )

    with limiter.acquire(client_ip="10.0.0.1", normalized_email="u@e.edu") as res:
        res.record_failure()

    # Unexpected exception must release in_flight without recording a failure.
    with pytest.raises(RuntimeError):
        with limiter.acquire(client_ip="10.0.0.1", normalized_email="u@e.edu"):
            raise RuntimeError("boom")

    # Slot is still available; success clears account failures.
    with limiter.acquire(client_ip="10.0.0.1", normalized_email="u@e.edu") as res:
        res.record_success()

    # Two new failures are allowed because success reset the account counter.
    for _ in range(2):
        with limiter.acquire(client_ip="10.0.0.1", normalized_email="u@e.edu") as res:
            res.record_failure()

    with pytest.raises(RateLimitExceededError):
        limiter.acquire(client_ip="10.0.0.1", normalized_email="u@e.edu")


def test_concurrent_account_attempts_cannot_exceed_limit() -> None:
    limiter = InMemoryLoginRateLimiter(
        account_max_attempts=5,
        ip_max_attempts=50,
        window_seconds=900,
    )
    threads_count = 20
    barrier = threading.Barrier(threads_count)
    hasher_calls = 0
    rate_limited = 0
    counter_lock = threading.Lock()

    def worker() -> None:
        nonlocal hasher_calls, rate_limited
        barrier.wait()
        try:
            with limiter.acquire(
                client_ip="127.0.0.1",
                normalized_email="victim@example.edu",
            ) as res:
                with counter_lock:
                    hasher_calls += 1
                time.sleep(0.02)  # simulate slow Argon2id verification
                res.record_failure()
        except RateLimitExceededError:
            with counter_lock:
                rate_limited += 1

    threads = [threading.Thread(target=worker) for _ in range(threads_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert hasher_calls == 5
    assert rate_limited == 15


def test_concurrent_ip_attempts_across_distinct_emails_cannot_exceed_ip_limit() -> None:
    limiter = InMemoryLoginRateLimiter(
        account_max_attempts=5,
        ip_max_attempts=6,
        window_seconds=900,
    )
    threads_count = 20
    barrier = threading.Barrier(threads_count)
    hasher_calls = 0
    rate_limited = 0
    counter_lock = threading.Lock()

    def worker(idx: int) -> None:
        nonlocal hasher_calls, rate_limited
        barrier.wait()
        try:
            with limiter.acquire(
                client_ip="192.0.2.10",
                normalized_email=f"user{idx}@example.edu",
            ) as res:
                with counter_lock:
                    hasher_calls += 1
                time.sleep(0.02)
                res.record_failure()
        except RateLimitExceededError:
            with counter_lock:
                rate_limited += 1

    threads = [
        threading.Thread(target=worker, args=(i,)) for i in range(threads_count)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert hasher_calls == 6
    assert rate_limited == 14


def test_lru_eviction_never_evicts_active_in_flight_reservations() -> None:
    clock = _FakeMonotonicClock()
    limiter = InMemoryLoginRateLimiter(
        account_max_attempts=1,
        ip_max_attempts=10,
        window_seconds=900,
        max_keys=3,
        clock=clock,
    )

    # Hold an active in-flight reservation for target account A.
    active_reservation = limiter.acquire(
        client_ip="10.0.0.1",
        normalized_email="active@example.edu",
    )
    try:
        # Flood with other keys exceeding max_keys=3 to trigger LRU eviction.
        for i in range(10):
            with limiter.acquire(
                client_ip=f"10.0.1.{i}",
                normalized_email=f"other{i}@example.edu",
            ) as other_res:
                other_res.record_failure()

        # Active reservation for A must STILL be tracked and block a 2nd concurrent attempt!
        with pytest.raises(RateLimitExceededError):
            limiter.acquire(
                client_ip="10.0.0.1",
                normalized_email="active@example.edu",
            )
    finally:
        active_reservation.record_failure()

    # After active_reservation recorded failure, A must remain blocked (limit=1).
    with pytest.raises(RateLimitExceededError):
        limiter.acquire(
            client_ip="10.0.0.1",
            normalized_email="active@example.edu",
        )
