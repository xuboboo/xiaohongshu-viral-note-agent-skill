from __future__ import annotations

import asyncio
import time
from collections import OrderedDict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

from xhs_skill.core.errors import CircuitOpenError, OverloadedError, RateLimitExceededError

T = TypeVar("T")


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class Bulkhead:
    """Bound concurrent work and queued waiters without creating unbounded tasks."""

    def __init__(self, name: str, max_active: int, max_waiters: int, wait_timeout: float) -> None:
        if max_active < 1 or max_waiters < 0:
            raise ValueError("Invalid bulkhead limits")
        self.name = name
        self.max_active = max_active
        self.max_waiters = max_waiters
        self.wait_timeout = wait_timeout
        self._active = 0
        self._waiters = 0
        self._condition = asyncio.Condition()

    @property
    def active(self) -> int:
        return self._active

    @property
    def waiters(self) -> int:
        return self._waiters

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        queued = False
        async with self._condition:
            if self._active >= self.max_active:
                if self._waiters >= self.max_waiters:
                    raise OverloadedError(
                        f"Bulkhead {self.name!r} is saturated",
                        details={
                            "scope": self.name,
                            "active": self._active,
                            "waiters": self._waiters,
                            "max_active": self.max_active,
                            "max_waiters": self.max_waiters,
                        },
                    )
                self._waiters += 1
                queued = True
                try:
                    async with asyncio.timeout(self.wait_timeout):
                        while self._active >= self.max_active:
                            await self._condition.wait()
                except TimeoutError as exc:
                    raise OverloadedError(
                        f"Timed out waiting for bulkhead {self.name!r}",
                        details={"scope": self.name, "retry_after_seconds": 1},
                    ) from exc
                finally:
                    self._waiters -= 1
            self._active += 1
        try:
            yield
        finally:
            async with self._condition:
                self._active -= 1
                self._condition.notify(1 if queued else self.max_active)


class KeyedBulkheadPool:
    """LRU-bounded per-key bulkheads for tenants, accounts, and providers."""

    def __init__(
        self,
        prefix: str,
        max_keys: int,
        max_active: int,
        max_waiters: int,
        wait_timeout: float,
    ) -> None:
        self.prefix = prefix
        self.max_keys = max_keys
        self.max_active = max_active
        self.max_waiters = max_waiters
        self.wait_timeout = wait_timeout
        self._items: OrderedDict[str, Bulkhead] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Bulkhead:
        async with self._lock:
            item = self._items.get(key)
            if item is None:
                item = Bulkhead(
                    f"{self.prefix}:{key}",
                    self.max_active,
                    self.max_waiters,
                    self.wait_timeout,
                )
                self._items[key] = item
                self._evict_idle()
            else:
                self._items.move_to_end(key)
            return item

    def _evict_idle(self) -> None:
        while len(self._items) > self.max_keys:
            oldest_key, oldest = next(iter(self._items.items()))
            if oldest.active or oldest.waiters:
                break
            self._items.pop(oldest_key, None)


@dataclass(slots=True)
class TokenBucketState:
    tokens: float
    updated_at: float


class LocalTokenBucket:
    """Monotonic-time token bucket suitable for one process."""

    def __init__(self, rate: float, burst: int, max_keys: int = 10_000) -> None:
        if rate <= 0 or burst < 1:
            raise ValueError("Invalid token bucket settings")
        self.rate = rate
        self.burst = float(burst)
        self.max_keys = max_keys
        self._states: OrderedDict[str, TokenBucketState] = OrderedDict()
        self._lock = asyncio.Lock()

    async def consume(self, key: str, cost: float = 1.0) -> tuple[bool, float, float]:
        now = time.monotonic()
        async with self._lock:
            state = self._states.get(key)
            if state is None:
                state = TokenBucketState(tokens=self.burst, updated_at=now)
                self._states[key] = state
            else:
                elapsed = max(0.0, now - state.updated_at)
                state.tokens = min(self.burst, state.tokens + elapsed * self.rate)
                state.updated_at = now
                self._states.move_to_end(key)
            allowed = state.tokens >= cost
            if allowed:
                state.tokens -= cost
                retry_after = 0.0
            else:
                retry_after = max(0.001, (cost - state.tokens) / self.rate)
            self._evict()
            return allowed, state.tokens, retry_after

    def _evict(self) -> None:
        while len(self._states) > self.max_keys:
            self._states.popitem(last=False)

    async def require(self, key: str, cost: float = 1.0) -> tuple[float, float]:
        allowed, remaining, retry_after = await self.consume(key, cost)
        if not allowed:
            raise RateLimitExceededError(
                "Rate limit exceeded",
                details={"key": key, "retry_after_seconds": retry_after, "remaining": remaining},
            )
        return remaining, retry_after


class CircuitBreaker:
    """Sliding-window circuit breaker with a single half-open probe."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_seconds: float = 30.0,
        window_seconds: float = 60.0,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self.window_seconds = window_seconds
        self._failures: deque[float] = deque()
        self._state = CircuitState.CLOSED
        self._opened_at = 0.0
        self._half_open_inflight = False
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    async def before_call(self) -> None:
        now = time.monotonic()
        async with self._lock:
            self._prune(now)
            if self._state == CircuitState.OPEN:
                if now - self._opened_at < self.recovery_seconds:
                    raise CircuitOpenError(
                        f"Circuit {self.name!r} is open",
                        details={
                            "retry_after_seconds": self.recovery_seconds - (now - self._opened_at)
                        },
                    )
                self._state = CircuitState.HALF_OPEN
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_inflight:
                    raise CircuitOpenError(
                        f"Circuit {self.name!r} is half-open",
                        details={"retry_after_seconds": 1},
                    )
                self._half_open_inflight = True

    async def record_success(self) -> None:
        async with self._lock:
            self._failures.clear()
            self._half_open_inflight = False
            self._state = CircuitState.CLOSED

    async def record_failure(self) -> None:
        now = time.monotonic()
        async with self._lock:
            self._half_open_inflight = False
            self._failures.append(now)
            self._prune(now)
            if (
                self._state == CircuitState.HALF_OPEN
                or len(self._failures) >= self.failure_threshold
            ):
                self._state = CircuitState.OPEN
                self._opened_at = now

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._failures and self._failures[0] < cutoff:
            self._failures.popleft()


class CircuitBreakerRegistry:
    def __init__(
        self,
        failure_threshold: int,
        recovery_seconds: float,
        window_seconds: float,
        max_keys: int = 1024,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._items: OrderedDict[str, CircuitBreaker] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> CircuitBreaker:
        async with self._lock:
            item = self._items.get(key)
            if item is None:
                item = CircuitBreaker(
                    key,
                    self.failure_threshold,
                    self.recovery_seconds,
                    self.window_seconds,
                )
                self._items[key] = item
                while len(self._items) > self.max_keys:
                    self._items.popitem(last=False)
            else:
                self._items.move_to_end(key)
            return item
