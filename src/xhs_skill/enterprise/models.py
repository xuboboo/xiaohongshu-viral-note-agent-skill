from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class TenantStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DELETED = "DELETED"


class TenantPlan(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    TEAM = "TEAM"
    ENTERPRISE = "ENTERPRISE"


class TenantPolicy(BaseModel):
    allowed_regions: list[str] = Field(default_factory=lambda: ["global"])
    data_residency_region: str = "global"
    daily_cost_limit_usd: float = Field(default=100.0, ge=0)
    monthly_cost_limit_usd: float = Field(default=2_000.0, ge=0)
    max_users: int = Field(default=500, ge=1, le=1_000_000)
    max_concurrent_jobs: int = Field(default=128, ge=1, le=100_000)
    publish_approval_quorum: int = Field(default=2, ge=1, le=10)
    require_separation_of_duties: bool = True
    require_phishing_resistant_mfa_for_publish: bool = True
    retention_days: int = Field(default=365, ge=1, le=3650)
    legal_hold: bool = False
    allowed_model_providers: list[str] = Field(default_factory=list)
    allowed_search_providers: list[str] = Field(default_factory=list)
    allowed_publish_accounts: list[str] = Field(default_factory=list)
    blocked_content_categories: list[str] = Field(default_factory=list)

    @field_validator("allowed_regions")
    @classmethod
    def normalize_regions(cls, value: list[str]) -> list[str]:
        normalized = sorted({item.strip().lower() for item in value if item.strip()})
        return normalized or ["global"]


class Tenant(BaseModel):
    id: str
    display_name: str
    plan: TenantPlan = TenantPlan.ENTERPRISE
    status: TenantStatus = TenantStatus.ACTIVE
    domains: list[str] = Field(default_factory=list)
    policy: TenantPolicy = Field(default_factory=TenantPolicy)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EnterpriseUser(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    user_name: str
    display_name: str = ""
    active: bool = True
    external_id: str | None = None
    emails: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EnterpriseGroup(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    display_name: str
    external_id: str | None = None
    members: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PolicyDecision(BaseModel):
    allowed: bool
    reason: str
    matched_rules: list[str] = Field(default_factory=list)
    obligations: list[str] = Field(default_factory=list)


class UsageReservation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    operation: str
    estimated_cost_usd: float = Field(ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    status: str = "RESERVED"
    actual_cost_usd: float | None = Field(default=None, ge=0)
    provider: str | None = None
    model: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BudgetSummary(BaseModel):
    tenant_id: str
    date: str
    month: str
    daily_limit_usd: float
    monthly_limit_usd: float
    daily_committed_usd: float
    monthly_committed_usd: float
    daily_remaining_usd: float
    monthly_remaining_usd: float
    active_reservations: int


class AuditEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    sequence: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tenant_id: str
    actor_id: str
    actor_type: str = "user"
    action: str
    resource_type: str
    resource_id: str | None = None
    outcome: str
    request_id: str | None = None
    source_ip_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    previous_hash: str
    event_hash: str
    signature: str


class AuditVerification(BaseModel):
    tenant_id: str
    valid: bool
    events_checked: int
    first_sequence: int | None = None
    last_sequence: int | None = None
    failure_sequence: int | None = None
    failure_reason: str | None = None
    root_hash: str | None = None


class ApprovalState(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ApprovalDecision(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    approver_id: str
    decision: str
    comment: str = ""
    auth_level: int = Field(default=2, ge=1, le=3)
    amr: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EnterpriseApproval(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    resource_type: str
    resource_id: str
    requested_by: str
    required_quorum: int = Field(default=2, ge=1, le=10)
    separation_of_duties: bool = True
    require_phishing_resistant_mfa: bool = True
    state: ApprovalState = ApprovalState.PENDING
    content_hash: str | None = None
    expires_at: datetime
    decisions: list[ApprovalDecision] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PluginPermission(StrEnum):
    NETWORK = "network"
    MODEL = "model"
    SEARCH = "search"
    STORAGE = "storage"
    ACCOUNT_READ = "account_read"
    PUBLISH = "publish"


class PluginManifest(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    version: str
    entrypoint: str
    api_version: str = "1"
    publisher: str
    permissions: list[PluginPermission] = Field(default_factory=list)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature: str
    public_key_id: str
    minimum_skill_version: str = "5.5.1"
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetentionRecord(BaseModel):
    tenant_id: str
    resource_type: str
    resource_id: str
    created_at: datetime
    delete_after: datetime
    legal_hold: bool = False
    deleted_at: datetime | None = None
