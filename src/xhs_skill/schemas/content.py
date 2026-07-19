from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from xhs_skill.schemas.research import ContentMechanism, HotNoteCandidate, TrendTopic


class ContentFormat(StrEnum):
    GRAPHIC = "graphic"
    VIDEO = "video"


class DistributionMode(StrEnum):
    SEARCH = "search"
    RECOMMENDATION = "recommendation"
    HYBRID = "hybrid"


class CommercialStatus(StrEnum):
    NON_COMMERCIAL = "NON_COMMERCIAL"
    ORGANIC_MENTION = "ORGANIC_MENTION"
    CREATOR_SEEDING = "CREATOR_SEEDING"
    COMMERCIAL_COLLABORATION = "COMMERCIAL_COLLABORATION"
    BRAND_OFFICIAL = "BRAND_OFFICIAL"
    STORE_CONVERSION = "STORE_CONVERSION"
    ECOMMERCE_CONVERSION = "ECOMMERCE_CONVERSION"
    LEAD_GENERATION = "LEAD_GENERATION"
    LIVE_PROMOTION = "LIVE_PROMOTION"


class GenerateRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=300)
    objective: str = "search_growth"
    format: ContentFormat = ContentFormat.GRAPHIC
    distribution_mode: DistributionMode = DistributionMode.HYBRID
    commercial_status: CommercialStatus = CommercialStatus.NON_COMMERCIAL
    account_id: str | None = None
    target_audience: str | None = None
    product: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    brand_voice: dict[str, Any] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    research_current_trends: bool = True
    # Host-agent websearch hits (url+title required). Used when no live search API key.
    web_results: list[dict[str, Any]] = Field(default_factory=list)
    candidate_count: int = Field(default=6, ge=1, le=20)
    provider: str | None = None
    model: str | None = None
    # 选题一跳：来自 topic_suggestions 的角度/说明，写入 strategy
    suggested_topic: str | None = Field(default=None, max_length=300)
    topic_angle: str | None = Field(default=None, max_length=120)
    topic_reason: str | None = Field(default=None, max_length=400)
    # 内容形态与叙事框架（创作增强）
    note_style: str | None = Field(
        default=None,
        max_length=32,
        description="review|seeding|avoid_pitfall|checklist|tutorial|store_visit|comparison|decision",
    )
    narrative_framework: str | None = Field(
        default=None,
        max_length=16,
        description="pas|aida|bab|quest|four_p|scqa|auto",
    )
    variant_index: int = Field(default=0, ge=0, le=20)
    # 口播时长：15 / 30 / 45 / 60 秒
    video_duration_seconds: int | None = Field(default=None, ge=15, le=60)


class TitleCandidate(BaseModel):
    id: str
    title: str
    mechanism: str
    target_audience: str = ""
    primary_keyword: str = ""
    scores: dict[str, float] = Field(default_factory=dict)
    risks: list[str] = Field(default_factory=list)


class CoverOption(BaseModel):
    headline: str
    subheadline: str = ""
    supporting_tag: str = ""
    visual_subject: str = ""
    composition: str = ""
    text_hierarchy: str = ""
    image_requirements: list[str] = Field(default_factory=list)


class GraphicPage(BaseModel):
    page: int
    purpose: str
    headline: str
    body_copy: str
    visual_direction: str
    layout: str = ""
    required_assets: list[str] = Field(default_factory=list)
    product_visibility: str = "none"


class VideoScene(BaseModel):
    start: float
    end: float
    visual: str
    narration: str
    subtitle: str
    b_roll: str = ""
    product_visibility: str = "none"


class VideoScript(BaseModel):
    duration_seconds: int
    hook_0_3s: str
    scenes: list[VideoScene]
    ending: str
    cover_copy: str
    post_caption: str


class EvidenceReference(BaseModel):
    evidence_id: str
    source: str
    excerpt: str
    locator: str | None = None
    excerpt_sha256: str
    confidence: str = "MEDIUM"
    valid_until: str | None = None


class Claim(BaseModel):
    id: str
    text: str
    claim_type: str
    sources: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
    verified: bool = False
    confidence: str = "LOW"
    allowed_expression: str | None = None
    publication_status: str = "REVIEW"


class DeliveryPackage(BaseModel):
    task_id: str
    trace_id: str
    assumptions: list[str] = Field(default_factory=list)
    research_summary: dict[str, Any] = Field(default_factory=dict)
    hot_notes: list[HotNoteCandidate] = Field(default_factory=list)
    trend_insights: list[TrendTopic] = Field(default_factory=list)
    mechanisms: list[ContentMechanism] = Field(default_factory=list)
    strategy: dict[str, Any] = Field(default_factory=dict)
    title_candidates: list[TitleCandidate] = Field(default_factory=list)
    selected_title: str
    cover_options: list[CoverOption] = Field(default_factory=list)
    body: str
    graphic_pages: list[GraphicPage] = Field(default_factory=list)
    video_script: VideoScript | None = None
    media_assets: list[str] = Field(default_factory=list)
    cover_asset: str | None = None
    topics: list[str] = Field(default_factory=list)
    location: str | None = None
    product_ids: list[str] = Field(default_factory=list)
    keyword_map: dict[str, Any] = Field(default_factory=dict)
    hashtags: list[str] = Field(default_factory=list)
    pinned_comment: str = ""
    cta: str = ""
    claims: list[Claim] = Field(default_factory=list)
    originality_report: dict[str, Any] = Field(default_factory=dict)
    compliance_report: dict[str, Any] = Field(default_factory=dict)
    ai_labeling: dict[str, Any] = Field(default_factory=dict)
    quality_report: dict[str, Any] = Field(default_factory=dict)
    content_hash: str
    publication_status: str = "HUMAN_REVIEW_REQUIRED"
    human_review_required: list[str] = Field(default_factory=list)
