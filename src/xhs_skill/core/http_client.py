from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

import httpx

from xhs_skill.core.config import Settings, get_settings


class HttpClientPool:
    """One shared HTTP/2-capable connection pool per process."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> httpx.AsyncClient:
        if self._client is not None and not self._client.is_closed:
            return self._client
        async with self._lock:
            if self._client is None or self._client.is_closed:
                limits = httpx.Limits(
                    max_connections=self.settings.http_max_connections,
                    max_keepalive_connections=self.settings.http_max_keepalive_connections,
                    keepalive_expiry=self.settings.http_keepalive_expiry_seconds,
                )
                timeout = httpx.Timeout(
                    connect=self.settings.http_connect_timeout_seconds,
                    read=self.settings.request_timeout_seconds,
                    write=self.settings.request_timeout_seconds,
                    pool=self.settings.http_pool_timeout_seconds,
                )
                self._client = httpx.AsyncClient(
                    limits=limits,
                    timeout=timeout,
                    http2=self.settings.http2_enabled,
                    follow_redirects=False,
                )
        return self._client

    async def close(self) -> None:
        async with self._lock:
            if self._client is not None and not self._client.is_closed:
                await self._client.aclose()

    @asynccontextmanager
    async def stream(self, method: str, url: str, **kwargs: Any):
        client = await self.get()
        async with client.stream(method, url, **kwargs) as response:
            yield response


_http_pool: HttpClientPool | None = None


def get_http_pool() -> HttpClientPool:
    global _http_pool
    if _http_pool is None:
        _http_pool = HttpClientPool()
    return _http_pool
