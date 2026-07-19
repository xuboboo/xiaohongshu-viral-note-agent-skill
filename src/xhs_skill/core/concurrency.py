from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.rate_limit import build_rate_limiter
from xhs_skill.core.resilience import Bulkhead, CircuitBreakerRegistry, KeyedBulkheadPool


class ConcurrencyController:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        wait = self.settings.concurrency_wait_timeout_seconds
        queued = self.settings.max_queued_waiters
        self.api = Bulkhead("api", self.settings.max_inflight_requests, queued, wait)
        self.sse = Bulkhead("sse", self.settings.sse_max_connections, queued, wait)
        self.research = Bulkhead("research", self.settings.research_concurrency, queued, wait)
        self.generation = Bulkhead("generation", self.settings.generation_concurrency, queued, wait)
        self.browser = Bulkhead("browser", self.settings.browser_concurrency, queued, wait)
        self.publish = Bulkhead("publish", self.settings.publish_concurrency, queued, wait)
        self.tenants = KeyedBulkheadPool(
            "tenant",
            max_keys=self.settings.max_tracked_tenants,
            max_active=self.settings.per_tenant_concurrency,
            max_waiters=self.settings.per_tenant_max_waiters,
            wait_timeout=wait,
        )
        self.sse_tenants = KeyedBulkheadPool(
            "sse-tenant",
            max_keys=self.settings.max_tracked_tenants,
            max_active=self.settings.per_tenant_sse_connections,
            max_waiters=self.settings.per_tenant_max_waiters,
            wait_timeout=wait,
        )
        self.providers = KeyedBulkheadPool(
            "provider",
            max_keys=self.settings.max_tracked_providers,
            max_active=self.settings.per_provider_concurrency,
            max_waiters=self.settings.per_provider_max_waiters,
            wait_timeout=wait,
        )
        self.rate_limiter = build_rate_limiter(
            "http",
            self.settings.rate_limit_requests_per_second,
            self.settings.rate_limit_burst,
            self.settings.max_rate_limit_keys,
            self.settings,
        )
        self.provider_rate_limiter = build_rate_limiter(
            "provider",
            self.settings.provider_rate_limit_requests_per_second,
            self.settings.provider_rate_limit_burst,
            self.settings.max_tracked_providers,
            self.settings,
        )
        self.circuits = CircuitBreakerRegistry(
            self.settings.circuit_breaker_failure_threshold,
            self.settings.circuit_breaker_recovery_seconds,
            self.settings.circuit_breaker_window_seconds,
        )

    @asynccontextmanager
    async def request_slot(self, tenant_id: str, *, streaming: bool = False) -> AsyncIterator[None]:
        tenant = await (
            self.sse_tenants.get(tenant_id) if streaming else self.tenants.get(tenant_id)
        )
        global_bulkhead = self.sse if streaming else self.api
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(global_bulkhead.slot())
            await stack.enter_async_context(tenant.slot())
            yield

    @asynccontextmanager
    async def operation_slot(
        self,
        operation: str,
        *,
        tenant_id: str = "public",
        provider: str | None = None,
    ) -> AsyncIterator[None]:
        operation_bulkhead = {
            "research": self.research,
            "generation": self.generation,
            "browser": self.browser,
            "publish": self.publish,
        }.get(operation, self.api)
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(operation_bulkhead.slot())
            if provider:
                provider_bulkhead = await self.providers.get(provider)
                await stack.enter_async_context(provider_bulkhead.slot())
            yield

    def snapshot(self) -> dict[str, dict[str, int]]:
        return {
            name: {"active": item.active, "waiters": item.waiters, "capacity": item.max_active}
            for name, item in {
                "api": self.api,
                "sse": self.sse,
                "research": self.research,
                "generation": self.generation,
                "browser": self.browser,
                "publish": self.publish,
            }.items()
        }


_controller: ConcurrencyController | None = None


def get_concurrency_controller() -> ConcurrencyController:
    global _controller
    if _controller is None:
        _controller = ConcurrencyController()
    return _controller
