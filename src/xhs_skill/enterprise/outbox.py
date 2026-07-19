from __future__ import annotations

import asyncio
import socket
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.enterprise.postgres import EnterprisePostgresStore
from xhs_skill.streaming.broker import EventBroker

OutboxHandler = Callable[[dict[str, Any]], Awaitable[None]]


class OutboxDispatcher:
    """Transactional outbox dispatcher with leases, retry and durable dead letters."""

    def __init__(
        self,
        settings: Settings | None = None,
        store: EnterprisePostgresStore | None = None,
        broker: EventBroker | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.store = store or EnterprisePostgresStore(self.settings)
        self.broker = broker or EventBroker(self.settings)
        self.handlers: dict[str, OutboxHandler] = {}
        self._stop = asyncio.Event()

    def register(self, event_type: str, handler: OutboxHandler) -> None:
        self.handlers[event_type] = handler

    async def _default_handler(self, item: dict[str, Any]) -> None:
        await self.broker.publish(
            str(item["aggregate_id"]),
            str(item["event_type"]),
            dict(item["payload"]),
        )

    async def dispatch_one(self, tenant_id: str, item: dict[str, Any]) -> None:
        handler = self.handlers.get(str(item["event_type"]), self._default_handler)
        try:
            await handler(item)
        except Exception as exc:
            await self.store.fail_outbox(
                tenant_id,
                int(item["id"]),
                {"code": type(exc).__name__, "message": str(exc)},
            )
            return
        await self.store.complete_outbox(tenant_id, int(item["id"]))

    async def run(self, worker_id: str | None = None) -> None:
        worker = worker_id or f"{socket.gethostname()}-{uuid4().hex[:8]}"
        while not self._stop.is_set():
            processed = 0
            for tenant_id in await self.store.list_tenant_ids():
                items = await self.store.claim_outbox_v2(
                    tenant_id=tenant_id,
                    worker_id=worker,
                    limit=self.settings.outbox_worker_batch_size,
                    lease_seconds=self.settings.outbox_lease_seconds,
                )
                processed += len(items)
                if items:
                    await asyncio.gather(
                        *(self.dispatch_one(tenant_id, item) for item in items),
                        return_exceptions=True,
                    )
            if not processed:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=1.0)
                except TimeoutError:
                    pass

    async def stop(self) -> None:
        self._stop.set()
        await self.store.close()
