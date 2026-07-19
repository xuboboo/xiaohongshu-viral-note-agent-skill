from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.identifiers import validate_identifier
from xhs_skill.enterprise.filelock import process_file_lock
from xhs_skill.enterprise.models import (
    EnterpriseApproval,
    EnterpriseGroup,
    EnterpriseUser,
    Tenant,
    TenantPlan,
    TenantPolicy,
)

T = TypeVar("T", bound=BaseModel)


class EnterpriseRepository:
    """Tenant-isolated JSON repository with atomic writes and restrictive permissions.

    PostgreSQL remains the recommended production backend; this repository is deterministic,
    portable and safe for a single-node Skill installation and test environments.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.root = self.settings.enterprise_data_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self._lock = threading.RLock()

    def _tenant_dir(self, tenant_id: str) -> Path:
        safe = validate_identifier(tenant_id, field="tenant_id")
        path = (self.root / "tenants" / safe).resolve()
        base = (self.root / "tenants").resolve()
        if path.parent != base:
            raise ValueError("Invalid tenant path")
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, 0o700)
        return path

    def _collection_path(self, tenant_id: str, collection: str) -> Path:
        if collection not in {"tenant", "users", "groups", "approvals", "reservations"}:
            raise ValueError("Unsupported collection")
        return self._tenant_dir(tenant_id) / f"{collection}.json"

    def _lock_path(self, tenant_id: str) -> Path:
        return self._tenant_dir(tenant_id) / ".repository.lock"

    @staticmethod
    def _read(path: Path, default):
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _atomic_write(path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2, default=str)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, path)
            os.chmod(path, 0o600)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def get_tenant(self, tenant_id: str) -> Tenant:
        path = self._collection_path(tenant_id, "tenant")
        with self._lock, process_file_lock(self._lock_path(tenant_id)):
            payload = self._read(path, None)
            if payload is None:
                tenant = Tenant(
                    id=validate_identifier(tenant_id, field="tenant_id"),
                    display_name=tenant_id,
                    plan=TenantPlan.ENTERPRISE,
                    policy=TenantPolicy(
                        allowed_regions=[self.settings.enterprise_default_region],
                        data_residency_region=self.settings.enterprise_default_region,
                        daily_cost_limit_usd=self.settings.enterprise_default_daily_budget_usd,
                        monthly_cost_limit_usd=self.settings.enterprise_default_monthly_budget_usd,
                        publish_approval_quorum=self.settings.enterprise_publish_approval_quorum,
                        require_separation_of_duties=self.settings.enterprise_separation_of_duties,
                        require_phishing_resistant_mfa_for_publish=(
                            self.settings.enterprise_require_phishing_resistant_mfa
                        ),
                    ),
                )
                self._atomic_write(path, tenant.model_dump(mode="json"))
                return tenant
            return Tenant.model_validate(payload)

    def save_tenant(self, tenant: Tenant) -> Tenant:
        tenant.updated_at = datetime.now(UTC)
        path = self._collection_path(tenant.id, "tenant")
        with self._lock, process_file_lock(self._lock_path(tenant.id)):
            self._atomic_write(path, tenant.model_dump(mode="json"))
        return tenant

    def _list(self, tenant_id: str, collection: str, model: type[T]) -> list[T]:
        path = self._collection_path(tenant_id, collection)
        with self._lock:
            return [model.model_validate(item) for item in self._read(path, [])]

    def _save_list(self, tenant_id: str, collection: str, items: Sequence[BaseModel]) -> None:
        path = self._collection_path(tenant_id, collection)
        with self._lock:
            self._atomic_write(path, [item.model_dump(mode="json") for item in items])

    def list_users(self, tenant_id: str) -> list[EnterpriseUser]:
        return self._list(tenant_id, "users", EnterpriseUser)

    def get_user(self, tenant_id: str, user_id: str) -> EnterpriseUser | None:
        safe_id = validate_identifier(user_id, field="user_id")
        return next((item for item in self.list_users(tenant_id) if item.id == safe_id), None)

    def find_user_by_name(self, tenant_id: str, user_name: str) -> EnterpriseUser | None:
        normalized = user_name.casefold()
        return next(
            (item for item in self.list_users(tenant_id) if item.user_name.casefold() == normalized),
            None,
        )

    def save_user(self, user: EnterpriseUser) -> EnterpriseUser:
        with self._lock, process_file_lock(self._lock_path(user.tenant_id)):
            users = self.list_users(user.tenant_id)
            now = datetime.now(UTC)
            user.updated_at = now
            for index, existing in enumerate(users):
                if existing.id == user.id:
                    user.created_at = existing.created_at
                    users[index] = user
                    break
            else:
                users.append(user)
            self._save_list(user.tenant_id, "users", users)
            return user


    def delete_user(self, tenant_id: str, user_id: str) -> bool:
        with self._lock, process_file_lock(self._lock_path(tenant_id)):
            users = self.list_users(tenant_id)
            filtered = [item for item in users if item.id != user_id]
            if len(filtered) == len(users):
                return False
            self._save_list(tenant_id, "users", filtered)
            groups = self.list_groups(tenant_id)
            for group in groups:
                if user_id in group.members:
                    group.members = [item for item in group.members if item != user_id]
            self._save_list(tenant_id, "groups", groups)
            return True


    def list_groups(self, tenant_id: str) -> list[EnterpriseGroup]:
        return self._list(tenant_id, "groups", EnterpriseGroup)

    def get_group(self, tenant_id: str, group_id: str) -> EnterpriseGroup | None:
        safe_id = validate_identifier(group_id, field="group_id")
        return next((item for item in self.list_groups(tenant_id) if item.id == safe_id), None)

    def save_group(self, group: EnterpriseGroup) -> EnterpriseGroup:
        with self._lock, process_file_lock(self._lock_path(group.tenant_id)):
            groups = self.list_groups(group.tenant_id)
            now = datetime.now(UTC)
            group.updated_at = now
            for index, existing in enumerate(groups):
                if existing.id == group.id:
                    group.created_at = existing.created_at
                    groups[index] = group
                    break
            else:
                groups.append(group)
            self._save_list(group.tenant_id, "groups", groups)
            return group


    def delete_group(self, tenant_id: str, group_id: str) -> bool:
        with self._lock, process_file_lock(self._lock_path(tenant_id)):
            groups = self.list_groups(tenant_id)
            filtered = [item for item in groups if item.id != group_id]
            if len(filtered) == len(groups):
                return False
            self._save_list(tenant_id, "groups", filtered)
            return True


    def list_approvals(self, tenant_id: str) -> list[EnterpriseApproval]:
        return self._list(tenant_id, "approvals", EnterpriseApproval)

    def get_approval(self, tenant_id: str, approval_id: str) -> EnterpriseApproval | None:
        safe_id = validate_identifier(approval_id, field="approval_id")
        return next(
            (item for item in self.list_approvals(tenant_id) if item.id == safe_id),
            None,
        )

    def save_approval(self, approval: EnterpriseApproval) -> EnterpriseApproval:
        with self._lock, process_file_lock(self._lock_path(approval.tenant_id)):
            approvals = self.list_approvals(approval.tenant_id)
            approval.updated_at = datetime.now(UTC)
            for index, existing in enumerate(approvals):
                if existing.id == approval.id:
                    approval.created_at = existing.created_at
                    approvals[index] = approval
                    break
            else:
                approvals.append(approval)
            self._save_list(approval.tenant_id, "approvals", approvals)
            return approval
