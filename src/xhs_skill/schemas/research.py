from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ScoreType(StrEnum):
    METRIC_HOT_SCORE = "METRIC_HOT_SCORE"
    PUBLIC_INDEX_HOT_SCORE = "PUBLIC_INDEX_HOT_SCORE"


class TrendClass(StrEnum):
    EMERGING = "EMERGING"
    RISING = "RISING"
    STABLE = "STABLE"
    SEASONAL = "SEASONAL"
    SATURATED = "SATURATED"
    DECLINING = "DECLINING"
    ANOMALOUS = "ANOMALOUS"


class SearchQuery(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    time_range: str = "7d"
    limit: int = Field(default=30, ge=1, le=100)
    language: str = "zh-hans"
    country: str = "CN"


class SearchResult(BaseModel):
    url: str
    title: str
    snippet: str | None = None
    published_at: datetime | None = None
    source_provider: str
    source_rank: int | None = None
    metadata: dict = Field(default_factory=dict)


class HotNoteCandidate(BaseModel):
    id: str
    url: str
    canonical_url: str | None = None
    title: str
    snippet: str | None = None
    body: str | None = None
    author_name: str | None = None
    published_at: datetime | None = None

    likes: int | None = None
    saves: int | None = None
    comments: int | None = None
    shares: int | None = None
    views: int | None = None
    followers: int | None = None

    source_provider: str
    source_rank: int | None = None
    indexed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    fetched_at: datetime | None = None

    commercial_probability: float | None = Field(default=None, ge=0, le=1)
    data_confidence: float = Field(default=0.5, ge=0, le=1)
    rights_status: str = "PUBLIC_INDEX_ONLY"
    score_type: ScoreType | None = None
    hot_score: float | None = None
    score_components: dict[str, float] = Field(default_factory=dict)
    duplicate_cluster: str | None = None


class ContentMechanism(BaseModel):
    audience: str = "未明确"
    audience_stage: str = "问题认知"
    user_problem: str = ""
    topic_angle: str = ""
    content_promise: str = ""
    title_mechanism: str = ""
    cover_mechanism: str = ""
    opening_mechanism: str = ""
    body_structure: list[str] = Field(default_factory=list)
    trust_signals: list[str] = Field(default_factory=list)
    emotional_strategy: str = "克制"
    search_intent: str = ""
    product_exposure_position: float | None = None
    cta_type: str | None = None
    reusable_principles: list[str] = Field(default_factory=list)
    prohibited_reuse: list[str] = Field(default_factory=list)


class TrendTopic(BaseModel):
    topic: str
    trend_class: TrendClass
    score: float
    growth_rate: float = 0.0
    acceleration: float = 0.0
    cross_source_support: float = 0.0
    saturation: float = 0.0
    change_point_detected: bool = False
    change_point_at: datetime | None = None
    momentum: float = 0.0
    content_gap_score: float = 0.0
    evidence_note_ids: list[str] = Field(default_factory=list)


class HotNotesReport(BaseModel):
    query: str
    time_range: str
    score_type: ScoreType
    notes: list[HotNoteCandidate]
    trends: list[TrendTopic] = Field(default_factory=list)
    mechanisms: list[ContentMechanism] = Field(default_factory=list)
    content_gaps: list[dict] = Field(default_factory=list)
    # 爆款/话题解读（公开索引估算，非官方热榜）
    hot_insights: dict = Field(default_factory=dict)
    topic_suggestions: list[dict] = Field(default_factory=list)
    coverage_warning: str
    search_quality: dict = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
