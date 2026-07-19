from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class AccountAnalytics(BaseModel):
    account_id: str
    followers: int | None = Field(default=None, ge=0)
    published_note_count: int | None = Field(default=None, ge=0)
    recent_publish_count_7d: int | None = Field(default=None, ge=0)
    recent_publish_count_30d: int | None = Field(default=None, ge=0)
    average_publish_interval_hours: float | None = Field(default=None, ge=0)
    views_30d: int | None = Field(default=None, ge=0)
    likes_30d: int | None = Field(default=None, ge=0)
    saves_30d: int | None = Field(default=None, ge=0)
    comments_30d: int | None = Field(default=None, ge=0)
    shares_30d: int | None = Field(default=None, ge=0)
    follows_gained_30d: int | None = Field(default=None, ge=0)
    profile_visits_30d: int | None = Field(default=None, ge=0)
    search_views_30d: int | None = Field(default=None, ge=0)
    recommendation_views_30d: int | None = Field(default=None, ge=0)
    commercial_note_ratio: float | None = Field(default=None, ge=0, le=1)
    deleted_note_count_90d: int | None = Field(default=None, ge=0)
    violation_count_90d: int | None = Field(default=None, ge=0)
    latest_violation_at: datetime | None = None
    category_distribution: dict[str, float] = Field(default_factory=dict)
    note_performance: list[dict] = Field(default_factory=list)


class DimensionScore(BaseModel):
    score: float = Field(ge=0, le=100)
    weight: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)


class AccountWeightReport(BaseModel):
    score_type: str = "ESTIMATED_ACCOUNT_WEIGHT"
    overall_score: float | None = Field(default=None, ge=0, le=100)
    confidence: str
    data_completeness: float = Field(ge=0, le=1)
    dimensions: dict[str, DimensionScore] = Field(default_factory=dict)
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    status: str = "OK"
    disclaimer: str = (
        "该分数为系统根据授权数据计算的账号健康与内容分发能力估算，不是小红书官方内部账号权重。"
    )


class AccountProfile(BaseModel):
    account_id: str
    tenant_id: str = "local"
    primary_audiences: list[str] = Field(default_factory=list)
    content_pillars: list[str] = Field(default_factory=list)
    preferred_formats: list[str] = Field(default_factory=list)
    winning_hooks: list[str] = Field(default_factory=list)
    avoid_patterns: list[str] = Field(default_factory=list)
    tone: str = "具体、克制、可执行"
    optimal_publish_days: list[int] = Field(default_factory=list)
    optimal_publish_hours: list[int] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AccountWeightSnapshot(BaseModel):
    account_id: str
    score: float | None = None
    confidence: str
    data_completeness: float
    dimensions: dict[str, float] = Field(default_factory=dict)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
