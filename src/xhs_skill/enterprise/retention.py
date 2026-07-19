from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from xhs_skill.enterprise.models import RetentionRecord
from xhs_skill.enterprise.repository import EnterpriseRepository


class RetentionService:
    def __init__(self, repository: EnterpriseRepository | None = None) -> None:
        self.repository = repository or EnterpriseRepository()

    def record(
        self,
        *,
        tenant_id: str,
        resource_type: str,
        resource_id: str,
        created_at: datetime | None = None,
    ) -> RetentionRecord:
        tenant = self.repository.get_tenant(tenant_id)
        created = created_at or datetime.now(UTC)
        return RetentionRecord(
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            created_at=created,
            delete_after=created + timedelta(days=tenant.policy.retention_days),
            legal_hold=tenant.policy.legal_hold,
        )

    @staticmethod
    def eligible(record: RetentionRecord, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        return not record.legal_hold and record.deleted_at is None and record.delete_after <= now

    def delete_file_if_eligible(
        self,
        record: RetentionRecord,
        path: Path,
        *,
        secure_delete: Callable[[Path], None] | None = None,
    ) -> RetentionRecord:
        if not self.eligible(record):
            return record
        if path.exists() and path.is_file() and not path.is_symlink():
            if secure_delete:
                secure_delete(path)
            else:
                path.unlink()
        record.deleted_at = datetime.now(UTC)
        return record
