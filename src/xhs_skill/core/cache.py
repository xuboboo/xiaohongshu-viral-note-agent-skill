from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.storage.redis_runtime import get_redis_runtime

T = TypeVar("T")


@dataclass(slots=True)
class CacheEntry:
    value: str
    expires_at: float


class LocalTTLCache:
    def __init__(self, max_entries: int) -> None:
        self.max_entries = max_entries
        self._items: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> str | None:
        now = time.monotonic()
        async with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            if entry.expires_at <= now:
                self._items.pop(key, None)
                return None
            self._items.move_to_end(key)
            return entry.value

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        async with self._lock:
            self._items[key] = CacheEntry(value=value, expires_at=time.monotonic() + ttl_seconds)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)


class Cache:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.local = LocalTTLCache(self.settings.cache_max_entries)
        self.distributed = bool(self.settings.redis_url and self.settings.distributed_cache_enabled)

    @staticmethod
    def key(namespace: str, payload: Any) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"{namespace}:{hashlib.sha256(encoded.encode()).hexdigest()}"

    async def get(self, key: str) -> str | None:
        local = await self.local.get(key)
        if local is not None:
            return local
        if not self.distributed:
            return None
        redis = await get_redis_runtime().get()
        raw = await redis.get(f"{self.settings.redis_stream_prefix}:cache:{key}")
        value = cast(str | None, raw)
        if value is not None:
            await self.local.set(key, value, min(30, self.settings.search_cache_ttl_seconds))
        return value

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        await self.local.set(key, value, ttl_seconds)
        if self.distributed:
            redis = await get_redis_runtime().get()
            await redis.set(
                f"{self.settings.redis_stream_prefix}:cache:{key}", value, ex=ttl_seconds
            )


class SingleFlight[T]:
    """Collapse concurrent identical work into one coroutine per process."""

    def __init__(self) -> None:
        self._inflight: dict[str, asyncio.Future[T]] = {}
        self._lock = asyncio.Lock()

    async def run(self, key: str, factory: Callable[[], Awaitable[T]]) -> T:
        leader = False
        async with self._lock:
            future = self._inflight.get(key)
            if future is None:
                future = asyncio.get_running_loop().create_future()
                self._inflight[key] = future
                leader = True
        if not leader:
            return await asyncio.shield(future)
        try:
            result = await factory()
            future.set_result(result)
            return result
        except BaseException as exc:
            if not future.done():
                future.set_exception(exc)
            raise
        finally:
            async with self._lock:
                self._inflight.pop(key, None)


_cache: Cache | None = None


def get_cache() -> Cache:
    global _cache
    if _cache is None:
        _cache = Cache()
    return _cache
