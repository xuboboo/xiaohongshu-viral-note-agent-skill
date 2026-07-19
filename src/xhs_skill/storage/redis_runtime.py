from __future__ import annotations

import asyncio
from typing import Any

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.errors import ConfigurationError


class RedisRuntime:
    """Shared async Redis connection pool for one application process."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: Any | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> Any:
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is None:
                if not self.settings.redis_url:
                    raise ConfigurationError(
                        "REDIS_URL is required for the selected distributed backend"
                    )
                try:
                    from redis.asyncio import ConnectionPool, Redis
                except ImportError as exc:  # pragma: no cover
                    raise ConfigurationError(
                        "Redis backend requires the redis extra",
                        details={"install": "pip install -e '.[redis]'"},
                    ) from exc
                pool = ConnectionPool.from_url(
                    self.settings.redis_url,
                    decode_responses=True,
                    max_connections=self.settings.redis_max_connections,
                    socket_connect_timeout=self.settings.redis_connect_timeout_seconds,
                    socket_timeout=self.settings.redis_socket_timeout_seconds,
                    health_check_interval=30,
                )
                self._client = Redis(connection_pool=pool)
        return self._client

    async def ping(self) -> bool:
        client = await self.get()
        return bool(await client.ping())

    async def close(self) -> None:
        async with self._lock:
            if self._client is not None:
                await self._client.aclose()
                await self._client.connection_pool.disconnect(inuse_connections=True)
                self._client = None


_runtime: RedisRuntime | None = None


def get_redis_runtime(settings: Settings | None = None) -> RedisRuntime:
    global _runtime
    requested = settings or get_settings()
    if _runtime is None or _runtime.settings.redis_url != requested.redis_url:
        _runtime = RedisRuntime(requested)
    return _runtime
