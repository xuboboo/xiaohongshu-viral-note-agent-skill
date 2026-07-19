from __future__ import annotations

import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.identifiers import validate_identifier
from xhs_skill.enterprise.filelock import process_file_lock
from xhs_skill.enterprise.models import BudgetSummary, UsageReservation
from xhs_skill.enterprise.repository import EnterpriseRepository


class BudgetExceededError(PermissionError):
    pass


class CostLedger:
    """Durable tenant cost reservations with hard daily/monthly limits."""

    def __init__(
        self,
        settings: Settings | None = None,
        repository: EnterpriseRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or EnterpriseRepository(self.settings)
        self.root = (self.settings.enterprise_data_dir / "cost-ledger").resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self._lock = threading.RLock()

    def _path(self, tenant_id: str) -> Path:
        safe = validate_identifier(tenant_id, field="tenant_id")
        path = (self.root / f"{safe}.jsonl").resolve()
        if path.parent != self.root:
            raise ValueError("Invalid cost-ledger path")
        return path

    def _all(self, tenant_id: str) -> list[UsageReservation]:
        path = self._path(tenant_id)
        if not path.exists():
            return []
        return [
            UsageReservation.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _rewrite(self, tenant_id: str, records: list[UsageReservation]) -> None:
        path = self._path(tenant_id)
        temp = path.with_suffix(".tmp")
        temp.write_text("".join(record.model_dump_json() + "\n" for record in records), encoding="utf-8")
        os.chmod(temp, 0o600)
        os.replace(temp, path)
        os.chmod(path, 0o600)

    @staticmethod
    def _committed(record: UsageReservation, now: datetime) -> float:
        if record.status == "SETTLED":
            return float(record.actual_cost_usd or 0)
        if record.status == "RESERVED" and record.expires_at > now:
            return float(record.estimated_cost_usd)
        return 0.0

    def summary(self, tenant_id: str, now: datetime | None = None) -> BudgetSummary:
        now = now or datetime.now(UTC)
        tenant = self.repository.get_tenant(tenant_id)
        records = self._all(tenant_id)
        daily = sum(
            self._committed(item, now)
            for item in records
            if item.created_at.date() == now.date()
        )
        monthly = sum(
            self._committed(item, now)
            for item in records
            if item.created_at.year == now.year and item.created_at.month == now.month
        )
        active = sum(1 for item in records if item.status == "RESERVED" and item.expires_at > now)
        return BudgetSummary(
            tenant_id=tenant_id,
            date=now.date().isoformat(),
            month=f"{now.year:04d}-{now.month:02d}",
            daily_limit_usd=tenant.policy.daily_cost_limit_usd,
            monthly_limit_usd=tenant.policy.monthly_cost_limit_usd,
            daily_committed_usd=round(daily, 8),
            monthly_committed_usd=round(monthly, 8),
            daily_remaining_usd=round(max(0.0, tenant.policy.daily_cost_limit_usd - daily), 8),
            monthly_remaining_usd=round(max(0.0, tenant.policy.monthly_cost_limit_usd - monthly), 8),
            active_reservations=active,
        )

    def reserve(
        self,
        *,
        tenant_id: str,
        operation: str,
        estimated_cost_usd: float,
        provider: str | None = None,
        model: str | None = None,
        metadata: dict | None = None,
    ) -> UsageReservation:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated cost cannot be negative")
        with self._lock, process_file_lock(self._path(tenant_id).with_suffix(".lock")):
            summary = self.summary(tenant_id)
            if estimated_cost_usd > summary.daily_remaining_usd:
                raise BudgetExceededError("Daily tenant cost budget would be exceeded")
            if estimated_cost_usd > summary.monthly_remaining_usd:
                raise BudgetExceededError("Monthly tenant cost budget would be exceeded")
            record = UsageReservation(
                tenant_id=tenant_id,
                operation=operation,
                estimated_cost_usd=estimated_cost_usd,
                expires_at=datetime.now(UTC) + timedelta(seconds=self.settings.cost_reservation_ttl_seconds),
                provider=provider,
                model=model,
                metadata=metadata or {},
            )
            path = self._path(tenant_id)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return record

    def settle(self, tenant_id: str, reservation_id: str, actual_cost_usd: float) -> UsageReservation:
        if actual_cost_usd < 0:
            raise ValueError("Actual cost cannot be negative")
        with self._lock, process_file_lock(self._path(tenant_id).with_suffix(".lock")):
            records = self._all(tenant_id)
            for record in records:
                if record.id == reservation_id:
                    if record.status != "RESERVED":
                        raise ValueError("Reservation is not active")
                    record.status = "SETTLED"
                    record.actual_cost_usd = actual_cost_usd
                    self._rewrite(tenant_id, records)
                    return record
        raise KeyError("Reservation not found")

    def release(self, tenant_id: str, reservation_id: str) -> UsageReservation:
        with self._lock, process_file_lock(self._path(tenant_id).with_suffix(".lock")):
            records = self._all(tenant_id)
            for record in records:
                if record.id == reservation_id:
                    if record.status != "RESERVED":
                        raise ValueError("Reservation is not active")
                    record.status = "RELEASED"
                    self._rewrite(tenant_id, records)
                    return record
        raise KeyError("Reservation not found")


_cost_ledger: CostLedger | None = None


def get_cost_ledger() -> CostLedger:
    global _cost_ledger
    if _cost_ledger is None:
        _cost_ledger = CostLedger()
    return _cost_ledger
