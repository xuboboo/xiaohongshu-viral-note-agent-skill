from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from xhs_skill.core.identifiers import atomic_write_private, private_mkdir, validate_identifier
from xhs_skill.schemas.account import (
    AccountAnalytics,
    AccountProfile,
    AccountWeightReport,
    AccountWeightSnapshot,
)


class AccountRepository:
    def __init__(self, root: str | Path = "./data/accounts") -> None:
        self.root = private_mkdir(root)

    def _tenant_root(self, tenant_id: str) -> Path:
        validate_identifier(tenant_id, field="tenant_id")
        return private_mkdir(self.root / tenant_id)

    def _path(self, tenant_id: str, account_id: str, suffix: str) -> Path:
        validate_identifier(account_id, field="account_id")
        return self._tenant_root(tenant_id) / f"{account_id}.{suffix}.json"

    def save_analytics(self, analytics: AccountAnalytics, tenant_id: str = "local") -> None:
        atomic_write_private(
            self._path(tenant_id, analytics.account_id, "analytics"),
            analytics.model_dump_json(indent=2).encode("utf-8"),
        )

    def load_analytics(self, account_id: str, tenant_id: str = "local") -> AccountAnalytics | None:
        path = self._path(tenant_id, account_id, "analytics")
        return AccountAnalytics.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None

    def save_report(self, account_id: str, report: AccountWeightReport, tenant_id: str = "local") -> None:
        atomic_write_private(
            self._path(tenant_id, account_id, "weight"),
            report.model_dump_json(indent=2).encode("utf-8"),
        )
        snapshot = AccountWeightSnapshot(
            account_id=account_id,
            score=report.overall_score,
            confidence=report.confidence,
            data_completeness=report.data_completeness,
            dimensions={key: value.score for key, value in report.dimensions.items()},
            recorded_at=datetime.now(UTC),
        )
        history = self._path(tenant_id, account_id, "weight-history").with_suffix(".jsonl")
        history.parent.mkdir(parents=True, exist_ok=True)
        with history.open("a", encoding="utf-8") as handle:
            handle.write(snapshot.model_dump_json() + "\n")
        history.chmod(0o600)

    def weight_history(self, account_id: str, tenant_id: str = "local") -> list[AccountWeightSnapshot]:
        path = self._path(tenant_id, account_id, "weight-history").with_suffix(".jsonl")
        if not path.exists():
            return []
        return [
            AccountWeightSnapshot.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def save_profile(self, profile: AccountProfile) -> None:
        atomic_write_private(
            self._path(profile.tenant_id, profile.account_id, "profile"),
            profile.model_dump_json(indent=2).encode("utf-8"),
        )

    def load_profile(self, account_id: str, tenant_id: str = "local") -> AccountProfile | None:
        path = self._path(tenant_id, account_id, "profile")
        return AccountProfile.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None
