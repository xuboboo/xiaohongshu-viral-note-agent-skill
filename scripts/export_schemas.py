from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from xhs_skill.enterprise.models import (
    AuditEvent,
    BudgetSummary,
    EnterpriseApproval,
    EnterpriseGroup,
    EnterpriseUser,
    PluginManifest,
    Tenant,
    TenantPolicy,
    UsageReservation,
)
from xhs_skill.operations import (
    AssetRecord,
    BanditDecision,
    ContentCalendarItem,
    Experiment,
    ExperimentAnalysis,
    PerformanceAttribution,
    PostPublishSyncTask,
    PublishedMetrics,
    Retrospective,
    SeriesPlan,
)
from xhs_skill.schemas.account import (
    AccountAnalytics,
    AccountProfile,
    AccountWeightReport,
    AccountWeightSnapshot,
)
from xhs_skill.schemas.content import DeliveryPackage, EvidenceReference, GenerateRequest
from xhs_skill.schemas.publishing import (
    AuthSession,
    PublishApproval,
    PublishDraft,
    PublishResult,
    PublishSchedule,
)
from xhs_skill.schemas.research import HotNoteCandidate, HotNotesReport
from xhs_skill.schemas.streaming import StreamEvent

SCHEMAS: dict[str, type[BaseModel]] = {
    "enterprise-tenant.schema.json": Tenant,
    "enterprise-tenant-policy.schema.json": TenantPolicy,
    "enterprise-user.schema.json": EnterpriseUser,
    "enterprise-group.schema.json": EnterpriseGroup,
    "enterprise-approval.schema.json": EnterpriseApproval,
    "enterprise-budget.schema.json": BudgetSummary,
    "enterprise-usage-reservation.schema.json": UsageReservation,
    "enterprise-audit-event.schema.json": AuditEvent,
    "enterprise-plugin-manifest.schema.json": PluginManifest,
    "generate-request.schema.json": GenerateRequest,
    "delivery-package.schema.json": DeliveryPackage,
    "hot-note.schema.json": HotNoteCandidate,
    "hot-notes-report.schema.json": HotNotesReport,
    "account-analytics.schema.json": AccountAnalytics,
    "account-weight.schema.json": AccountWeightReport,
    "auth-session.schema.json": AuthSession,
    "publish-draft.schema.json": PublishDraft,
    "publish-approval.schema.json": PublishApproval,
    "publish-result.schema.json": PublishResult,
    "publish-schedule.schema.json": PublishSchedule,
    "stream-event.schema.json": StreamEvent,
    "account-profile.schema.json": AccountProfile,
    "account-weight-snapshot.schema.json": AccountWeightSnapshot,
    "evidence-reference.schema.json": EvidenceReference,
    "published-metrics.schema.json": PublishedMetrics,
    "performance-attribution.schema.json": PerformanceAttribution,
    "content-calendar-item.schema.json": ContentCalendarItem,
    "content-series.schema.json": SeriesPlan,
    "content-experiment.schema.json": Experiment,
    "experiment-analysis.schema.json": ExperimentAnalysis,
    "bandit-decision.schema.json": BanditDecision,
    "asset-record.schema.json": AssetRecord,
    "retrospective.schema.json": Retrospective,
    "post-publish-sync-task.schema.json": PostPublishSyncTask,
}


def main() -> None:
    root = Path("schemas")
    root.mkdir(exist_ok=True)
    for filename, model in SCHEMAS.items():
        (root / filename).write_text(
            json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(root / filename)


if __name__ == "__main__":
    main()
