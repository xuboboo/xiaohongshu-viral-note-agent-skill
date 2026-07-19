from __future__ import annotations

from typing import Any

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.enterprise.postgres import EnterprisePostgresStore
from xhs_skill.enterprise.quota import BudgetExceededError, CostLedger


class CostBudgetService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.local = CostLedger(self.settings)
        self.postgres = EnterprisePostgresStore(self.settings) if self.settings.postgres_state_enabled else None

    async def reserve(self, **kwargs: Any) -> Any:
        if self.postgres is not None:
            try:
                return await self.postgres.reserve_cost(
                    **kwargs,
                    ttl_seconds=self.settings.cost_reservation_ttl_seconds,
                )
            except PermissionError as exc:
                raise BudgetExceededError(str(exc)) from exc
        return self.local.reserve(**kwargs)

    async def settle(self, tenant_id: str, reservation_id: str, actual_cost_usd: float) -> Any:
        if self.postgres is not None:
            return await self.postgres.settle_cost(tenant_id, reservation_id, actual_cost_usd)
        return self.local.settle(tenant_id, reservation_id, actual_cost_usd)

    async def release(self, tenant_id: str, reservation_id: str) -> Any:
        if self.postgres is not None:
            return await self.postgres.release_cost(tenant_id, reservation_id)
        return self.local.release(tenant_id, reservation_id)

    async def summary(self, tenant_id: str) -> dict[str, Any]:
        if self.postgres is not None:
            return await self.postgres.cost_summary(tenant_id)
        return self.local.summary(tenant_id).model_dump(mode="json")


_service: CostBudgetService | None = None


def get_cost_budget_service() -> CostBudgetService:
    global _service
    if _service is None:
        _service = CostBudgetService()
    return _service
