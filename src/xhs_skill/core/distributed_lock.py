from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.errors import OverloadedError
from xhs_skill.storage.redis_runtime import get_redis_runtime

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
else
  return 0
end
"""


class DistributedLockManager:
    """Redis lease locks with safe token release; local fallback for one process."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._local: OrderedDict[str, asyncio.Lock] = OrderedDict()
        self._local_guard = asyncio.Lock()
        self._distributed = bool(
            self.settings.redis_url and self.settings.distributed_locks_enabled
        )
        self._redis_runtime = get_redis_runtime(self.settings) if self._distributed else None

    async def _local_lock(self, key: str) -> asyncio.Lock:
        async with self._local_guard:
            lock = self._local.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._local[key] = lock
                while len(self._local) > self.settings.max_tracked_accounts:
                    oldest_key, oldest = next(iter(self._local.items()))
                    if oldest.locked():
                        break
                    self._local.pop(oldest_key, None)
            else:
                self._local.move_to_end(key)
            return lock

    @asynccontextmanager
    async def lock(
        self,
        key: str,
        *,
        ttl_seconds: float | None = None,
        wait_timeout: float | None = None,
    ) -> AsyncIterator[None]:
        ttl = ttl_seconds or self.settings.distributed_lock_ttl_seconds
        timeout = wait_timeout or self.settings.distributed_lock_wait_timeout_seconds
        if not self._distributed:
            lock = await self._local_lock(key)
            try:
                async with asyncio.timeout(timeout):
                    await lock.acquire()
            except TimeoutError as exc:
                raise OverloadedError(
                    f"Could not acquire lock {key!r}",
                    details={"retry_after_seconds": 1},
                ) from exc
            try:
                yield
            finally:
                lock.release()
            return

        if self._redis_runtime is None:
            raise RuntimeError("Distributed lock runtime is not initialized")
        redis = await self._redis_runtime.get()
        token = str(uuid4())
        namespaced = f"{self.settings.redis_stream_prefix}:lock:{key}"
        deadline = time.monotonic() + timeout
        acquired = False
        while time.monotonic() < deadline:
            acquired = bool(await redis.set(namespaced, token, nx=True, px=int(ttl * 1000)))
            if acquired:
                break
            await asyncio.sleep(0.05)
        if not acquired:
            raise OverloadedError(
                f"Could not acquire distributed lock {key!r}",
                details={"retry_after_seconds": 1},
            )
        try:
            yield
        finally:
            await redis.eval(_RELEASE_SCRIPT, 1, namespaced, token)

    async def close(self) -> None:
        return None


_manager: DistributedLockManager | None = None


def get_distributed_lock_manager() -> DistributedLockManager:
    global _manager
    if _manager is None:
        _manager = DistributedLockManager()
    return _manager
