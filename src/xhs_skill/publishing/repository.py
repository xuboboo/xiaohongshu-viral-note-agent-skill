from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from xhs_skill.core.identifiers import atomic_write_private, private_mkdir, validate_identifier
from xhs_skill.schemas.publishing import (
    PublishApproval,
    PublishDraft,
    PublishResult,
    PublishSchedule,
)


class PublishingRepository:
    """Private, atomic local repository for single-node installs.

    Multi-replica production deployments must replace this with the PostgreSQL repository
    introduced in v4.1.0. Files are tenant-scoped, identifier-validated and mode 0600.
    """

    def __init__(self, root: str | Path = "./data/publishing") -> None:
        self.root = private_mkdir(root)
        self._lock = threading.RLock()

    def _tenant_root(self, tenant_id: str) -> Path:
        validate_identifier(tenant_id, field="tenant_id")
        return private_mkdir(self.root / tenant_id)

    def _path(self, tenant_id: str, kind: str, id_: str) -> Path:
        validate_identifier(id_, field=f"{kind}_id")
        return self._tenant_root(tenant_id) / f"{kind}-{id_}.json"

    def save_draft(self, draft: PublishDraft) -> None:
        payload = draft.model_dump(mode="json")
        payload["preview_path"] = draft.preview_path
        import json

        atomic_write_private(
            self._path(draft.tenant_id, "draft", draft.id),
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    def load_draft(self, draft_id: str, tenant_id: str = "local") -> PublishDraft:
        return PublishDraft.model_validate_json(
            self._path(tenant_id, "draft", draft_id).read_text(encoding="utf-8")
        )

    def save_approval(self, approval: PublishApproval) -> None:
        persisted = approval.model_copy(update={"approval_token": None})
        atomic_write_private(
            self._path(approval.tenant_id, "approval", approval.draft_id),
            persisted.model_dump_json(indent=2).encode("utf-8"),
        )

    def load_approval(self, draft_id: str, tenant_id: str = "local") -> PublishApproval | None:
        path = self._path(tenant_id, "approval", draft_id)
        return (
            PublishApproval.model_validate_json(path.read_text(encoding="utf-8"))
            if path.exists()
            else None
        )

    def consume_approval(self, draft_id: str, tenant_id: str) -> PublishApproval:
        with self._lock:
            approval = self.load_approval(draft_id, tenant_id)
            if approval is None:
                raise FileNotFoundError(draft_id)
            if approval.used_at is not None:
                raise ValueError("Approval token has already been consumed")
            approval.used_at = datetime.now(UTC)
            self.save_approval(approval)
            return approval

    def save_result(self, result: PublishResult, tenant_id: str = "local") -> None:
        atomic_write_private(
            self._path(tenant_id, "result", result.job_id),
            result.model_dump_json(indent=2).encode("utf-8"),
        )

    def save_schedule(self, schedule: PublishSchedule) -> None:
        atomic_write_private(
            self._path(schedule.tenant_id, "schedule", schedule.id),
            schedule.model_dump_json(indent=2).encode("utf-8"),
        )

    def load_schedule(self, schedule_id: str, tenant_id: str = "local") -> PublishSchedule:
        return PublishSchedule.model_validate_json(
            self._path(tenant_id, "schedule", schedule_id).read_text(encoding="utf-8")
        )

    def submitted_results(self, account_id: str, tenant_id: str = "local") -> list[PublishResult]:
        validate_identifier(account_id, field="account_id")
        results: list[PublishResult] = []
        for path in self._tenant_root(tenant_id).glob("result-*.json"):
            try:
                item = PublishResult.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, ValidationError):
                continue
            if item.account_id == account_id and item.status in {
                "VERIFIED",
                "SUBMITTED_UNVERIFIED",
            }:
                results.append(item)
        return results

    def successful_results(self, account_id: str, tenant_id: str = "local") -> list[PublishResult]:
        return [
            item
            for item in self.submitted_results(account_id, tenant_id)
            if item.status == "VERIFIED"
        ]

    def find_by_fingerprint(
        self, account_id: str, fingerprint: str, tenant_id: str = "local"
    ) -> PublishResult | None:
        for item in self.submitted_results(account_id, tenant_id):
            if item.audit.get("fingerprint") == fingerprint:
                return item
        return None
