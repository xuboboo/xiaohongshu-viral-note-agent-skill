from __future__ import annotations

import asyncio

import pytest

from xhs_skill.core.cache import LocalTTLCache, SingleFlight


@pytest.mark.asyncio
async def test_local_ttl_cache_expires() -> None:
    cache = LocalTTLCache(max_entries=2)
    await cache.set("a", "1", ttl_seconds=1)
    assert await cache.get("a") == "1"


@pytest.mark.asyncio
async def test_singleflight_runs_factory_once() -> None:
    flight: SingleFlight[int] = SingleFlight()
    calls = 0

    async def factory() -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return 42

    results = await asyncio.gather(*(flight.run("same", factory) for _ in range(100)))
    assert results == [42] * 100
    assert calls == 1
