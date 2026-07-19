from __future__ import annotations

from typing import Protocol

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.errors import RateLimitExceededError
from xhs_skill.core.resilience import LocalTokenBucket
from xhs_skill.storage.redis_runtime import get_redis_runtime

_TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local ttl_ms = tonumber(ARGV[4])
local t = redis.call('TIME')
local now_ms = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local values = redis.call('HMGET', key, 'tokens', 'updated_at')
local tokens = tonumber(values[1])
local updated_at = tonumber(values[2])
if tokens == nil then
  tokens = burst
  updated_at = now_ms
end
local elapsed_ms = math.max(0, now_ms - updated_at)
tokens = math.min(burst, tokens + (elapsed_ms / 1000.0) * rate)
local allowed = 0
local retry_after_ms = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
else
  retry_after_ms = math.ceil(((cost - tokens) / rate) * 1000)
end
redis.call('HSET', key, 'tokens', tokens, 'updated_at', now_ms)
redis.call('PEXPIRE', key, ttl_ms)
return {allowed, tostring(tokens), retry_after_ms}
"""


class RateLimiter(Protocol):
    async def consume(self, key: str, cost: float = 1.0) -> tuple[bool, float, float]: ...
    async def require(self, key: str, cost: float = 1.0) -> tuple[float, float]: ...


class RedisTokenBucket:
    def __init__(
        self,
        namespace: str,
        rate: float,
        burst: int,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.namespace = namespace
        self.rate = rate
        self.burst = burst

    async def consume(self, key: str, cost: float = 1.0) -> tuple[bool, float, float]:
        client = await get_redis_runtime(self.settings).get()
        redis_key = f"{self.settings.redis_stream_prefix}:rate:{self.namespace}:{key}"
        ttl_ms = int(max(60_000, (self.burst / self.rate) * 4 * 1000))
        result = await client.eval(
            _TOKEN_BUCKET_SCRIPT,
            1,
            redis_key,
            self.rate,
            self.burst,
            cost,
            ttl_ms,
        )
        allowed = bool(int(result[0]))
        remaining = float(result[1])
        retry_after = float(result[2]) / 1000.0
        return allowed, remaining, retry_after

    async def require(self, key: str, cost: float = 1.0) -> tuple[float, float]:
        allowed, remaining, retry_after = await self.consume(key, cost)
        if not allowed:
            raise RateLimitExceededError(
                "Rate limit exceeded",
                details={"key": key, "retry_after_seconds": retry_after, "remaining": remaining},
            )
        return remaining, retry_after


def build_rate_limiter(
    namespace: str,
    rate: float,
    burst: int,
    max_keys: int,
    settings: Settings | None = None,
) -> RateLimiter:
    settings = settings or get_settings()
    if settings.redis_url and settings.distributed_rate_limit_enabled:
        return RedisTokenBucket(namespace, rate, burst, settings)
    return LocalTokenBucket(rate, burst, max_keys)
