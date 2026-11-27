"""Thread-safe, atomic reservation-based in-memory login rate limiter.

Implements Revision 3 §6.4:
- Eliminates TOCTOU races under concurrent login attempts by reserving capacity
  atomically before password verification (`failures + in_flight <= limit`).
- Enforces both (client_ip, normalized_email) and client_ip limits together.
- Bounded key storage with LRU eviction that NEVER evicts keys with active
  in-flight reservations (`in_flight > 0`).
"""

from __future__ import annotations

from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
import math
import threading
import time
from types import TracebackType
from typing import Protocol


class RateLimitExceededError(Exception):
    """Raised when a login attempt exceeds configured rate limits."""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = max(1, int(retry_after))
        super().__init__(
            f"Too many login attempts. Try again in {self.retry_after} seconds."
        )


class LoginRateLimitReservation(Protocol):
    """Reservation context manager returned by LoginRateLimiter.acquire()."""

    def record_failure(self) -> None: ...

    def record_success(self) -> None: ...

    def release(self) -> None: ...

    def __enter__(self) -> LoginRateLimitReservation: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...


class LoginRateLimiter(Protocol):
    """Abstraction for login attempt rate limiting."""

    def acquire(
        self,
        *,
        client_ip: str,
        normalized_email: str,
    ) -> LoginRateLimitReservation: ...


@dataclass
class _Bucket:
    failures: deque[float] = field(default_factory=deque)
    in_flight: int = 0


class _InMemoryReservation:
    """Single-use reservation handle ensuring in_flight counters never leak."""

    def __init__(
        self,
        limiter: InMemoryLoginRateLimiter,
        account_key: tuple[str, str],
        ip_key: tuple[str, str],
    ) -> None:
        self._limiter = limiter
        self._account_key = account_key
        self._ip_key = ip_key
        self._finalized = False

    def record_failure(self) -> None:
        if self._finalized:
            return
        self._finalized = True
        self._limiter._finalize_failure(self._account_key, self._ip_key)

    def record_success(self) -> None:
        if self._finalized:
            return
        self._finalized = True
        self._limiter._finalize_success(self._account_key, self._ip_key)

    def release(self) -> None:
        if self._finalized:
            return
        self._finalized = True
        self._limiter._release(self._account_key, self._ip_key)

    def __enter__(self) -> _InMemoryReservation:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.release()


class InMemoryLoginRateLimiter:
    """Process-local sliding-window rate limiter with atomic reservations."""

    def __init__(
        self,
        *,
        account_max_attempts: int = 5,
        ip_max_attempts: int = 30,
        window_seconds: int = 900,
        max_keys: int = 10000,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if account_max_attempts < 1:
            raise ValueError("account_max_attempts must be at least 1.")
        if ip_max_attempts < 1:
            raise ValueError("ip_max_attempts must be at least 1.")
        if window_seconds < 1:
            raise ValueError("window_seconds must be at least 1.")
        if max_keys < 2:
            raise ValueError("max_keys must be at least 2.")

        self._account_max = account_max_attempts
        self._ip_max = ip_max_attempts
        self._window_seconds = float(window_seconds)
        self._max_keys = max_keys
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._buckets: OrderedDict[tuple[str, str], _Bucket] = OrderedDict()

    def _prune_bucket(self, bucket: _Bucket, now: float) -> None:
        cutoff = now - self._window_seconds
        while bucket.failures and bucket.failures[0] <= cutoff:
            bucket.failures.popleft()

    def _retry_after_for_bucket(self, bucket: _Bucket, now: float) -> int:
        if bucket.failures:
            remaining = bucket.failures[0] + self._window_seconds - now
            return max(1, math.ceil(remaining))
        return 1

    def _evict_idle_keys(self, now: float, protected: set[tuple[str, str]]) -> None:
        """Evict expired or least-recently-used idle keys without touching active ones."""
        if len(self._buckets) <= self._max_keys:
            return

        # Pass 1: drop completely expired idle keys (in_flight == 0).
        expired_idle: list[tuple[str, str]] = []
        for key, bucket in self._buckets.items():
            if key in protected or bucket.in_flight > 0:
                continue
            self._prune_bucket(bucket, now)
            if not bucket.failures:
                expired_idle.append(key)
        for key in expired_idle:
            self._buckets.pop(key, None)

        if len(self._buckets) <= self._max_keys:
            return

        # Pass 2: LRU eviction strictly limited to keys with in_flight == 0.
        for key in list(self._buckets.keys()):
            if len(self._buckets) <= self._max_keys:
                break
            if key in protected:
                continue
            bucket = self._buckets[key]
            if bucket.in_flight == 0:
                self._buckets.pop(key, None)

    def acquire(
        self,
        *,
        client_ip: str,
        normalized_email: str,
    ) -> _InMemoryReservation:
        """Atomically reserve one login slot for both (ip, email) and ip keys."""
        ip_norm = (client_ip or "unknown").strip()
        email_norm = normalized_email.strip().lower()
        account_key = ("account", f"{ip_norm}\x00{email_norm}")
        ip_key = ("ip", ip_norm)

        with self._lock:
            now = self._clock()
            checks = (
                (account_key, self._account_max),
                (ip_key, self._ip_max),
            )

            retry_after = 0
            for key, limit in checks:
                bucket = self._buckets.get(key)
                if bucket is not None:
                    self._prune_bucket(bucket, now)
                    if len(bucket.failures) + bucket.in_flight >= limit:
                        retry_after = max(
                            retry_after,
                            self._retry_after_for_bucket(bucket, now),
                        )

            if retry_after > 0:
                raise RateLimitExceededError(retry_after=retry_after)

            for key, _limit in checks:
                bucket = self._buckets.get(key)
                if bucket is None:
                    bucket = _Bucket()
                    self._buckets[key] = bucket
                else:
                    self._buckets.move_to_end(key)
                bucket.in_flight += 1

            self._evict_idle_keys(now, protected={account_key, ip_key})

        return _InMemoryReservation(self, account_key, ip_key)

    def _finalize_failure(
        self,
        account_key: tuple[str, str],
        ip_key: tuple[str, str],
    ) -> None:
        with self._lock:
            now = self._clock()
            for key in (account_key, ip_key):
                bucket = self._buckets.get(key)
                if bucket is None:
                    bucket = _Bucket()
                    self._buckets[key] = bucket
                bucket.in_flight = max(0, bucket.in_flight - 1)
                self._prune_bucket(bucket, now)
                bucket.failures.append(now)
                self._buckets.move_to_end(key)

    def _finalize_success(
        self,
        account_key: tuple[str, str],
        ip_key: tuple[str, str],
    ) -> None:
        with self._lock:
            now = self._clock()
            account_bucket = self._buckets.get(account_key)
            if account_bucket is not None:
                account_bucket.in_flight = max(0, account_bucket.in_flight - 1)
                account_bucket.failures.clear()
                if account_bucket.in_flight == 0:
                    self._buckets.pop(account_key, None)

            ip_bucket = self._buckets.get(ip_key)
            if ip_bucket is not None:
                ip_bucket.in_flight = max(0, ip_bucket.in_flight - 1)
                self._prune_bucket(ip_bucket, now)
                if ip_bucket.in_flight == 0 and not ip_bucket.failures:
                    self._buckets.pop(ip_key, None)

    def _release(
        self,
        account_key: tuple[str, str],
        ip_key: tuple[str, str],
    ) -> None:
        with self._lock:
            now = self._clock()
            for key in (account_key, ip_key):
                bucket = self._buckets.get(key)
                if bucket is None:
                    continue
                bucket.in_flight = max(0, bucket.in_flight - 1)
                self._prune_bucket(bucket, now)
                if bucket.in_flight == 0 and not bucket.failures:
                    self._buckets.pop(key, None)
