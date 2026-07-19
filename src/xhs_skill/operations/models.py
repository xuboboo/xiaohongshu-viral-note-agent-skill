from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class PublishedMetrics(BaseModel):
    note_id: str
    account_id: str
    tenant_id: str = "local"
    snapshot_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    views: int | None = Field(default=None, ge=0)
    likes: int | None = Field(default=None, ge=0)
    saves: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    shares: int | None = Field(default=None, ge=0)
    follows: int | None = Field(default=None, ge=0)
    profile_visits: int | None = Field(default=None, ge=0)
    search_views: int | None = Field(default=None, ge=0)
    recommendation_views: int | None = Field(default=None, ge=0)
    source: str = "AUTHORIZED_IMPORT"
    content_features: dict[str, float | str | bool] = Field(default_factory=dict)


class AttributionContribution(BaseModel):
    feature: str
    contribution: float
    direction: str
    confidence: float = Field(ge=0, le=1)
    explanation: str


class PerformanceAttribution(BaseModel):
    note_id: str
    account_id: str
    primary_metric: str
    metric_value: float
    baseline_value: float
    lift: float
    contributions: list[AttributionContribution] = Field(default_factory=list)
    caveat: str = "该归因基于相关性和对照基线，不代表严格因果。"


class ContentCalendarItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str = "local"
    account_id: str
    scheduled_at: datetime
    topic: str
    content_pillar: str
    objective: str
    format: str = "graphic"
    status: str = "PLANNED"
    series_id: str | None = None
    experiment_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SeriesPlan(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str = "local"
    account_id: str
    title: str
    promise: str
    episodes: list[dict[str, Any]]
    cadence_days: int = Field(default=3, ge=1, le=30)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExperimentVariant(BaseModel):
    id: str
    name: str
    payload: dict[str, Any]
    allocation: float = Field(default=1.0, gt=0)


class Experiment(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str = "local"
    account_id: str
    name: str
    hypothesis: str
    primary_metric: str
    variants: list[ExperimentVariant]
    status: str = "DRAFT"
    started_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExperimentAssignment(BaseModel):
    experiment_id: str
    subject_id: str
    variant_id: str
    assigned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExperimentOutcome(BaseModel):
    experiment_id: str
    subject_id: str
    variant_id: str
    metric: str
    value: float
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BanditDecision(BaseModel):
    policy_id: str
    subject_id: str
    arm_id: str
    score: float
    exploration_bonus: float
    context: list[float]
    context_features: dict[str, float] = Field(default_factory=dict)
    context_schema_version: str | None = None
    decided_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AssetRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str = "local"
    account_id: str | None = None
    sha256: str
    filename: str
    media_type: str
    size_bytes: int
    storage_path: str
    tags: list[str] = Field(default_factory=list)
    rights_status: str = "USER_OWNED"
    source: str = "UPLOAD"
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Retrospective(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str = "local"
    account_id: str
    note_id: str
    summary: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    next_note_suggestions: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PostPublishSyncTask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str = "local"
    account_id: str
    note_id: str
    note_url: str | None = None
    # 发布时注入的标题/主题快照，供 LTR 回流
    content_features: dict[str, float | str | bool] = Field(default_factory=dict)
    due_at: datetime
    status: str = "PENDING"
    attempts: int = 0
    max_attempts: int = 8
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
