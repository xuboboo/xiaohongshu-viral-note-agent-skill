from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from xhs_skill.accounts import AccountService
from xhs_skill.browser import LoginFlow
from xhs_skill.core.auth import Principal
from xhs_skill.core.config import get_settings
from xhs_skill.enterprise.approvals import EnterpriseApprovalService
from xhs_skill.enterprise.audit import AuditLedger
from xhs_skill.enterprise.dlp import redact_text, scan_text
from xhs_skill.enterprise.policy import get_policy_engine
from xhs_skill.enterprise.quota import CostLedger
from xhs_skill.enterprise.repository import EnterpriseRepository
from xhs_skill.generation.diagnose_structure import structure_checks
from xhs_skill.jobs.dlq import RedisDeadLetterQueue
from xhs_skill.operations import (
    Experiment,
    ExperimentOutcome,
    OperationsService,
    PublishedMetrics,
)
from xhs_skill.orchestrator import ContentWorkflow
from xhs_skill.publishing import PublishingService
from xhs_skill.research import ResearchService
from xhs_skill.research.topic_suggest import suggest_topics_from_report
from xhs_skill.schemas.account import AccountAnalytics
from xhs_skill.schemas.content import CommercialStatus, DeliveryPackage, GenerateRequest
from xhs_skill.schemas.publishing import PublishMode
from xhs_skill.schemas.research import SearchQuery
from xhs_skill.search.adaptive import ClientWebSearchRequired
from xhs_skill.storage.assets import AssetStore
from xhs_skill.verifiers import (
    ai_style_report,
    check_text,
    extract_claims,
    originality_report_async,
)


def _tool(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
    *,
    high_impact: bool = False,
) -> dict[str, Any]:
    from xhs_skill.ux.catalog import annotate_tool_definition

    result: dict[str, Any] = {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
    }
    if high_impact:
        result["annotations"] = {
            "destructiveHint": name in {"logout_account"},
            "openWorldHint": True,
            "idempotentHint": name not in {"publish_note", "schedule_note"},
        }
    return annotate_tool_definition(result)


TOOL_DEFINITIONS = [
    _tool(
        "search_hot_notes",
        (
            "搜索公开网页索引或授权数据中的近期小红书热门笔记，并返回 hot_insights（爆款标签/热度带/原因）。"
            "若未配置搜索 API，且未传入 web_results，会返回 needs_web_search，"
            "宿主 agent 应先 websearch 再带着 web_results 重试。"
            "公开结果不代表站内全量热榜。"
        ),
        {
            "query": {"type": "string"},
            "time_range": {"type": "string", "default": "7d"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            "providers": {"type": "array", "items": {"type": "string"}},
            "web_results": {
                "type": "array",
                "description": (
                    "宿主 websearch 结果。每项至少 url+title；"
                    "可含 snippet/published_at/互动数字段。"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                        "snippet": {"type": "string"},
                        "published_at": {"type": "string"},
                        "source_rank": {"type": "integer"},
                        "likes": {"type": "integer"},
                        "saves": {"type": "integer"},
                        "comments": {"type": "integer"},
                        "shares": {"type": "integer"},
                        "views": {"type": "integer"},
                        "author_name": {"type": "string"},
                    },
                    "required": ["url", "title"],
                    "additionalProperties": True,
                },
            },
        },
        ["query"],
    ),
    _tool(
        "search_trending_topics",
        (
            "搜索并返回趋势主题、可点选选题建议 topic_suggestions、公开索引覆盖警告。"
            "无搜索密钥时可先 websearch，再传 web_results。"
        ),
        {
            "query": {"type": "string"},
            "time_range": {"type": "string", "default": "7d"},
            "providers": {"type": "array", "items": {"type": "string"}},
            "web_results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                        "snippet": {"type": "string"},
                    },
                    "required": ["url", "title"],
                    "additionalProperties": True,
                },
            },
        },
        ["query"],
    ),
    _tool(
        "analyze_hot_notes",
        (
            "分析热门笔记中的用户问题、标题机制、内容缺口与可点选选题。"
            "无搜索密钥时可先 websearch，再传 web_results。"
        ),
        {
            "query": {"type": "string"},
            "time_range": {"type": "string", "default": "7d"},
            "providers": {"type": "array", "items": {"type": "string"}},
            "web_results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                        "snippet": {"type": "string"},
                    },
                    "required": ["url", "title"],
                    "additionalProperties": True,
                },
            },
        },
        ["query"],
    ),
    _tool(
        "generate_xhs_note",
        (
            "研究趋势并生成原创小红书图文或视频内容包。"
            "若 research_current_trends=true 且未配置搜索 API，"
            "可传入 web_results（宿主 websearch 结果）或先收到 needs_web_search。"
            "可用 suggested_topic/topic_angle 承接 topic_suggestions 一跳生成。"
        ),
        {
            "topic": {"type": "string"},
            "objective": {"type": "string"},
            "format": {"type": "string", "enum": ["graphic", "video"]},
            "distribution_mode": {
                "type": "string",
                "enum": ["search", "recommendation", "hybrid"],
            },
            "commercial_status": {"type": "string"},
            "account_id": {"type": "string"},
            "target_audience": {"type": "string"},
            "product": {"type": "object"},
            "brand_voice": {"type": "object"},
            "evidence": {"type": "array", "items": {"type": "object"}},
            "constraints": {"type": "array", "items": {"type": "string"}},
            "candidate_count": {"type": "integer", "minimum": 1, "maximum": 20},
            "provider": {"type": "string"},
            "model": {"type": "string"},
            "research_current_trends": {"type": "boolean"},
            "suggested_topic": {"type": "string"},
            "topic_angle": {"type": "string"},
            "topic_reason": {"type": "string"},
            "note_style": {
                "type": "string",
                "description": "review|seeding|avoid_pitfall|checklist|tutorial|store_visit|comparison|decision",
            },
            "narrative_framework": {
                "type": "string",
                "description": "pas|aida|bab|quest|four_p|scqa|auto",
            },
            "variant_index": {"type": "integer", "minimum": 0, "maximum": 20},
            "video_duration_seconds": {
                "type": "integer",
                "enum": [15, 30, 45, 60],
                "description": "口播分镜时长模板（秒）",
            },
            "web_results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                        "snippet": {"type": "string"},
                    },
                    "required": ["url", "title"],
                    "additionalProperties": True,
                },
            },
        },
        ["topic"],
    ),
    _tool(
        "plan_content_outline",
        "仅生成创作大纲（框架阶段、开场钩子、情绪曲线、CTA），不生成全文；可先 outline 再 generate。",
        {
            "topic": {"type": "string"},
            "note_style": {"type": "string"},
            "narrative_framework": {"type": "string"},
            "target_audience": {"type": "string"},
            "product": {"type": "object"},
            "constraints": {"type": "array", "items": {"type": "string"}},
            "variant_index": {"type": "integer", "minimum": 0, "maximum": 20},
        },
        ["topic"],
    ),
    _tool(
        "rewrite_xhs_note",
        "去 AI 味、降低广告感并保持事实不变地改写笔记。",
        {
            "body": {"type": "string"},
            "title": {"type": "string"},
            "commercial_status": {"type": "string"},
            "constraints": {"type": "array", "items": {"type": "string"}},
            "references": {"type": "array", "items": {"type": "string"}},
        },
        ["body"],
    ),
    _tool(
        "diagnose_xhs_note",
        "诊断笔记的合规、原创性、AI 风格和结构问题。",
        {
            "title": {"type": "string"},
            "body": {"type": "string"},
            "references": {"type": "array", "items": {"type": "string"}},
            "candidate_image_asset_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
            "reference_image_asset_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        ["body"],
    ),
    _tool(
        "verify_claims",
        "提取客观声明并根据提供证据生成声明台账。",
        {
            "text": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "object"}},
        },
        ["text"],
    ),
    _tool(
        "check_originality",
        "检查与参考文本的字面和语义相似风险。",
        {
            "text": {"type": "string"},
            "references": {"type": "array", "items": {"type": "string"}},
            "candidate_image_asset_ids": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 20,
            },
            "reference_image_asset_ids": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 100,
            },
        },
        ["text"],
    ),
    _tool(
        "check_compliance",
        "检查虚构体验、功效、极限词、商业披露和其他高风险表达。",
        {
            "text": {"type": "string"},
            "commercial_status": {"type": "string"},
        },
        ["text"],
    ),
    _tool(
        "query_account_weight",
        "根据授权数据估算账号健康与内容分发能力；不是小红书官方内部权重。",
        {"account_id": {"type": "string"}, "analytics": {"type": "object"}},
        ["account_id"],
    ),
    _tool(
        "query_content_health",
        "根据授权笔记表现估算内容健康度（互动/收藏/节奏/搜索/风险等）；非官方质量分。",
        {"account_id": {"type": "string"}, "analytics": {"type": "object"}},
        ["account_id"],
    ),
    _tool(
        "diagnose_account",
        "联合账号权重与内容健康度诊断；返回 conflict_notes、combined_actions 与 generate_payload（可一跳生成）。",
        {
            "account_id": {"type": "string"},
            "analytics": {"type": "object"},
            "base_topic": {"type": "string", "description": "可选：诊断动作映射到该主题的 generate_payload"},
        },
        ["account_id"],
    ),
    _tool(
        "suggest_topics_by_health",
        (
            "根据账号内容健康度弱项/强项生成或重排选题（可叠加 query 热门研究）。"
            "返回 strategy + topic_suggestions（含 generate_payload）。非官方推荐算法。"
        ),
        {
            "account_id": {"type": "string"},
            "analytics": {"type": "object"},
            "base_topic": {"type": "string"},
            "query": {"type": "string", "description": "可选：叠加热门研究后按健康度重排"},
            "providers": {"type": "array", "items": {"type": "string"}},
            "web_results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                        "snippet": {"type": "string"},
                    },
                    "required": ["url", "title"],
                    "additionalProperties": True,
                },
            },
            "limit": {"type": "integer", "minimum": 3, "maximum": 12},
        },
        ["account_id"],
    ),
    _tool(
        "sync_account_analytics",
        "保存用户授权提供的账号分析数据。",
        {"account_id": {"type": "string"}, "analytics": {"type": "object"}},
        ["account_id", "analytics"],
    ),
    _tool(
        "start_account_login",
        "启动用户扫码登录。不会绕过验证码或风险验证。",
        {"account_id": {"type": "string"}},
        ["account_id"],
        high_impact=True,
    ),
    _tool(
        "check_account_login",
        "检查授权登录状态。",
        {"account_id": {"type": "string"}},
        ["account_id"],
    ),
    _tool(
        "logout_account",
        "退出并可删除本地加密会话。必须显式批准。",
        {
            "account_id": {"type": "string"},
            "delete_session": {"type": "boolean", "default": True},
            "approved": {"type": "boolean"},
        },
        ["account_id", "approved"],
        high_impact=True,
    ),
    _tool(
        "create_publish_draft",
        "为指定账号创建受控发布草稿。",
        {
            "account_id": {"type": "string"},
            "package": {"type": "object"},
            "mode": {"type": "string"},
        },
        ["account_id", "package"],
        high_impact=True,
    ),
    _tool(
        "preview_publish_draft",
        "填充创作平台并生成发布预览。",
        {"draft_id": {"type": "string"}},
        ["draft_id"],
        high_impact=True,
    ),
    _tool(
        "approve_publish_draft",
        "为当前内容 Hash 创建短期发布批准令牌。",
        {
            "draft_id": {"type": "string"},
            "ttl_minutes": {"type": "integer"},
            "ai_disclosure_confirmed": {"type": "boolean"},
            "commercial_disclosure_confirmed": {"type": "boolean"},
            "account_identity_confirmed": {"type": "boolean"},
            "enterprise_approval_id": {"type": "string"},
        },
        ["draft_id"],
        high_impact=True,
    ),
    _tool(
        "publish_note",
        "发布已预览且获得批准的内容。必须显式批准。",
        {
            "draft_id": {"type": "string"},
            "approval_token": {"type": "string"},
            "approved": {"type": "boolean"},
        },
        ["draft_id", "approval_token", "approved"],
        high_impact=True,
    ),
    _tool(
        "schedule_note",
        "定时发布已批准内容。必须显式批准。",
        {
            "draft_id": {"type": "string"},
            "approval_token": {"type": "string"},
            "scheduled_at": {"type": "string", "format": "date-time"},
            "approved": {"type": "boolean"},
        },
        ["draft_id", "approval_token", "scheduled_at", "approved"],
        high_impact=True,
    ),
    _tool(
        "get_enterprise_controls",
        "返回租户数据驻留、审批、MFA、预算和审计控制状态。",
        {},
    ),
    _tool(
        "get_enterprise_budget",
        "返回租户每日和每月成本预算、承诺与剩余额度。",
        {},
    ),
    _tool(
        "create_enterprise_approval",
        "为高风险资源创建多人审批工作流。",
        {
            "resource_type": {"type": "string"},
            "resource_id": {"type": "string"},
            "content_hash": {"type": "string"},
            "ttl_minutes": {"type": "integer", "minimum": 1, "maximum": 120},
        },
        ["resource_type", "resource_id"],
        high_impact=True,
    ),
    _tool(
        "decide_enterprise_approval",
        "使用独立审批者和抗钓鱼 MFA 对企业审批作出决定。",
        {
            "approval_id": {"type": "string"},
            "decision": {"type": "string", "enum": ["APPROVE", "REJECT"]},
            "comment": {"type": "string"},
        },
        ["approval_id", "decision"],
        high_impact=True,
    ),
    _tool(
        "verify_enterprise_audit",
        "验证租户不可篡改审计哈希链。",
        {},
    ),
    _tool(
        "enterprise_dlp_scan",
        "检测并脱敏文本中的个人信息、私钥和 API 密钥。",
        {"text": {"type": "string"}, "redact": {"type": "boolean"}},
        ["text"],
    ),
    _tool(
        "sync_published_metrics",
        "保存用户授权的发布后表现快照。",
        {"metrics": {"type": "object"}},
        ["metrics"],
    ),
    _tool(
        "get_performance_attribution",
        "将指定笔记与账号历史基线比较，输出谨慎的相关性归因。",
        {"account_id": {"type": "string"}, "note_id": {"type": "string"}},
        ["account_id", "note_id"],
    ),
    _tool(
        "get_account_weight_trend",
        "返回账号权重历史快照和趋势方向。",
        {"account_id": {"type": "string"}},
        ["account_id"],
    ),
    _tool(
        "create_content_calendar",
        "根据账号画像和主题创建内容日历；topics 可空时用 fallback_topics（如复盘 next_note_suggestions.topic）。",
        {
            "account_id": {"type": "string"},
            "topics": {"type": "array", "items": {"type": "string"}},
            "fallback_topics": {"type": "array", "items": {"type": "string"}},
            "days": {"type": "integer", "minimum": 7, "maximum": 365},
            "posts_per_week": {"type": "integer", "minimum": 1, "maximum": 7},
        },
        ["account_id"],
    ),
    _tool(
        "create_content_series",
        "创建连续系列选题与每集承接关系。",
        {
            "account_id": {"type": "string"},
            "title": {"type": "string"},
            "topic": {"type": "string"},
            "audience": {"type": "string"},
            "episode_count": {"type": "integer", "minimum": 2, "maximum": 30},
        },
        ["account_id", "title", "topic", "audience"],
    ),
    _tool(
        "create_abn_experiment",
        "创建 A/B/n 内容实验。",
        {"experiment": {"type": "object"}},
        ["experiment"],
    ),
    _tool(
        "assign_experiment_variant",
        "为实验主体稳定分配变体。",
        {
            "experiment_id": {"type": "string"},
            "subject_id": {"type": "string"},
        },
        ["experiment_id", "subject_id"],
    ),
    _tool(
        "record_experiment_outcome",
        "记录实验指标结果。",
        {"outcome": {"type": "object"}},
        ["outcome"],
    ),
    _tool(
        "analyze_abn_experiment",
        "分析 A/B/n 实验结果，输出置信区间、样本充分性与建议变体。",
        {
            "experiment_id": {"type": "string"},
            "minimum_samples_per_variant": {
                "type": "integer",
                "minimum": 2,
                "maximum": 100000,
                "default": 20,
            },
        },
        ["experiment_id"],
    ),
    _tool(
        "choose_content_bandit",
        "使用 LinUCB 上下文策略选择内容机制。可用 features 自动编码账号权重/时段/类目。",
        {
            "policy_id": {"type": "string"},
            "subject_id": {"type": "string"},
            "arms": {"type": "array", "items": {"type": "string"}},
            "context": {"type": "array", "items": {"type": "number"}},
            "features": {"type": "object"},
            "account_id": {"type": "string"},
            "auto_account_weight": {"type": "boolean", "default": True},
        },
        ["policy_id", "subject_id", "arms"],
    ),
    _tool(
        "update_content_bandit",
        "使用观测奖励更新 LinUCB 策略。context 与 features 二选一。",
        {
            "policy_id": {"type": "string"},
            "arm_id": {"type": "string"},
            "context": {"type": "array", "items": {"type": "number"}},
            "features": {"type": "object"},
            "account_id": {"type": "string"},
            "auto_account_weight": {"type": "boolean", "default": True},
            "reward": {"type": "number"},
        },
        ["policy_id", "arm_id", "reward"],
    ),
    _tool(
        "search_asset_library",
        "按标签查询租户素材库。",
        {"tags": {"type": "array", "items": {"type": "string"}}},
    ),
    _tool(
        "generate_retrospective",
        "根据发布后表现自动复盘并生成下一篇建议。",
        {"account_id": {"type": "string"}, "note_id": {"type": "string"}},
        ["account_id", "note_id"],
    ),
    _tool(
        "list_job_dead_letters",
        "列出 Redis 分布式任务死信。",
        {"count": {"type": "integer", "minimum": 1, "maximum": 1000}},
    ),
    _tool(
        "replay_job_dead_letter",
        "重放指定 Redis 任务死信。",
        {"message_id": {"type": "string"}, "approved": {"type": "boolean"}},
        ["message_id", "approved"],
        high_impact=True,
    ),
    _tool(
        "analyze_performance",
        "根据用户提供的发布表现数据生成谨慎复盘，不把相关性伪装成因果。",
        {"metrics": {"type": "object"}},
        ["metrics"],
    ),
    _tool(
        "draft_comment_reply",
        "生成授权评论回复草稿，仅供人工粘贴；auto_submit 恒为 false，不会自动发评。",
        {
            "original_comment": {"type": "string"},
            "note_context": {"type": "string"},
            "tone": {"type": "string", "enum": ["helpful", "brief", "empathetic"]},
            "comment_id": {"type": "string"},
            "note_id": {"type": "string"},
            "max_candidates": {"type": "integer", "minimum": 1, "maximum": 5},
        },
        ["original_comment"],
    ),
    _tool(
        "generate_xhs_note_variants",
        "同一主题生成 1–5 个交付包变体，按就绪分排序，便于标题/置顶评 A/B。",
        {
            "topic": {"type": "string"},
            "variant_count": {"type": "integer", "minimum": 1, "maximum": 5},
            "format": {"type": "string", "enum": ["graphic", "video"]},
            "target_audience": {"type": "string"},
            "commercial_status": {"type": "string"},
            "account_id": {"type": "string"},
            "note_style": {"type": "string"},
            "narrative_framework": {"type": "string"},
            "brand_voice": {"type": "object"},
            "product": {"type": "object"},
            "constraints": {"type": "array", "items": {"type": "string"}},
            "research_current_trends": {"type": "boolean"},
            "suggested_topic": {"type": "string"},
            "topic_angle": {"type": "string"},
            "provider": {"type": "string"},
            "web_results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                        "snippet": {"type": "string"},
                    },
                    "required": ["url", "title"],
                    "additionalProperties": True,
                },
            },
        },
        ["topic"],
    ),
    _tool(
        "generate_from_hot",
        (
            "热门→选题→一键生成：搜索公开热门/趋势后自动选题并生成交付包。"
            "dry_run=true 时只返回 topic_suggestions；false 时复用同一研究报吿生成，避免二次搜索。"
            "仍为公开索引估算，不是站内官方热榜。"
        ),
        {
            "query": {"type": "string"},
            "suggestion_index": {"type": "integer", "minimum": 0, "maximum": 20},
            "suggestion_topic": {"type": "string"},
            "dry_run": {"type": "boolean", "default": False},
            "use_account_health": {
                "type": "boolean",
                "default": False,
                "description": "为 true 且提供 account_id 时，按内容健康度重排选题并推荐 note_style",
            },
            "format": {"type": "string", "enum": ["graphic", "video"]},
            "video_duration_seconds": {"type": "integer", "enum": [15, 30, 45, 60]},
            "note_style": {"type": "string"},
            "narrative_framework": {"type": "string"},
            "target_audience": {"type": "string"},
            "commercial_status": {"type": "string"},
            "account_id": {"type": "string"},
            "brand_voice": {"type": "object"},
            "product": {"type": "object"},
            "constraints": {"type": "array", "items": {"type": "string"}},
            "provider": {"type": "string"},
            "providers": {"type": "array", "items": {"type": "string"}},
            "web_results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                        "snippet": {"type": "string"},
                    },
                    "required": ["url", "title"],
                    "additionalProperties": True,
                },
            },
        },
        ["query"],
    ),
    _tool(
        "get_publish_windows",
        "根据账号画像返回建议发帖星期与时段（启发式，非官方流量秘密）。",
        {"account_id": {"type": "string"}},
        ["account_id"],
    ),
]


TOOL_SCOPES: dict[str, tuple[str, ...]] = {
    "search_hot_notes": ("research:read",),
    "search_trending_topics": ("research:read",),
    "analyze_hot_notes": ("research:read",),
    "generate_xhs_note": ("content:generate",),
    "generate_xhs_note_variants": ("content:generate",),
    "generate_from_hot": ("content:generate",),
    "plan_content_outline": ("content:generate",),
    "rewrite_xhs_note": ("content:generate",),
    "diagnose_xhs_note": ("content:generate",),
    "verify_claims": ("content:generate",),
    "check_originality": ("content:generate",),
    "check_compliance": ("content:generate",),
    "query_account_weight": ("account:read",),
    "query_content_health": ("account:read",),
    "diagnose_account": ("account:read",),
    "suggest_topics_by_health": ("account:read",),
    "sync_account_analytics": ("account:sync",),
    "start_account_login": ("auth:manage",),
    "check_account_login": ("auth:manage",),
    "logout_account": ("auth:manage",),
    "create_publish_draft": ("publish:draft",),
    "preview_publish_draft": ("publish:draft",),
    "approve_publish_draft": ("publish:approve",),
    "publish_note": ("publish:execute",),
    "schedule_note": ("publish:execute",),
    "get_enterprise_controls": ("enterprise:admin",),
    "get_enterprise_budget": ("billing:read",),
    "create_enterprise_approval": ("publish:approve",),
    "decide_enterprise_approval": ("publish:approve",),
    "verify_enterprise_audit": ("audit:read",),
    "enterprise_dlp_scan": ("content:generate",),
    "sync_published_metrics": ("account:sync",),
    "get_performance_attribution": ("account:read",),
    "get_account_weight_trend": ("account:read",),
    "create_content_calendar": ("content:plan",),
    "create_content_series": ("content:plan",),
    "create_abn_experiment": ("experiments:write",),
    "assign_experiment_variant": ("experiments:write",),
    "record_experiment_outcome": ("experiments:write",),
    "analyze_abn_experiment": ("experiments:read",),
    "choose_content_bandit": ("experiments:write",),
    "update_content_bandit": ("experiments:write",),
    "search_asset_library": ("assets:read",),
    "generate_retrospective": ("account:read",),
    "list_job_dead_letters": ("jobs:admin",),
    "replay_job_dead_letter": ("jobs:admin",),
    "analyze_performance": ("account:read",),
    "draft_comment_reply": ("content:generate",),
    "get_publish_windows": ("account:read",),
}

TOOL_MIN_AUTH_LEVEL: dict[str, int] = {
    "start_account_login": 2,
    "logout_account": 2,
    "approve_publish_draft": 2,
    "publish_note": 2,
    "schedule_note": 2,
    "create_enterprise_approval": 2,
    "decide_enterprise_approval": 2,
    "replay_job_dead_letter": 2,
}


class MCPToolService:
    def __init__(self) -> None:
        self.research = ResearchService()
        self.workflow = ContentWorkflow()
        self.accounts = AccountService()
        self.login = LoginFlow()
        self.publishing = PublishingService(login_flow=self.login)
        self.enterprise_repository = EnterpriseRepository()
        self.enterprise_approvals = EnterpriseApprovalService(self.enterprise_repository)
        self.enterprise_audit = AuditLedger()
        self.enterprise_costs = CostLedger(repository=self.enterprise_repository)
        self.operations = OperationsService()
        self.asset_store = AssetStore()

    @staticmethod
    def _require_approval(arguments: dict[str, Any]) -> None:
        if arguments.get("approved") is not True:
            raise PermissionError("This high-impact tool requires approved=true")

    @staticmethod
    def _enterprise_authorize(
        principal: Principal,
        operation: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        settings = get_settings()
        # personal 配置档不跑企业策略（与 API enforce_enterprise_policy 一致）
        if settings.profile == "personal":
            return
        if not settings.enterprise_enabled or not settings.enterprise_policy_enforcement:
            return
        decision = get_policy_engine().evaluate(principal, operation, context=context)
        if not decision.allowed:
            raise PermissionError(decision.reason)

    async def call(
        self, name: str, arguments: dict[str, Any], principal: Principal
    ) -> dict[str, Any]:
        from xhs_skill.ux.envelope import enrich_tool_result

        data = await self._call_impl(name, arguments, principal)
        return enrich_tool_result(name, data)

    async def _call_impl(
        self, name: str, arguments: dict[str, Any], principal: Principal
    ) -> dict[str, Any]:
        required = TOOL_SCOPES.get(name)
        if required is None:
            raise KeyError(f"Unknown tool {name}")
        if not principal.has(*required):
            raise PermissionError(f"Missing required scope: {', '.join(required)}")
        if principal.auth_level < TOOL_MIN_AUTH_LEVEL.get(name, 1):
            raise PermissionError("Step-up authentication is required")
        operation_map = {
            "generate_xhs_note": "content.generate",
            "query_account_weight": "account.read",
            "analyze_performance": "account.read",
            "sync_account_analytics": "account.sync",
            "create_publish_draft": "publish.draft",
            "approve_publish_draft": "publish.approve",
            "publish_note": "publish.execute",
            "schedule_note": "publish.execute",
            "get_enterprise_controls": "tenant.read",
            "get_enterprise_budget": "budget.read",
            "create_enterprise_approval": "approval.create",
            "decide_enterprise_approval": "approval.decide",
            "verify_enterprise_audit": "audit.verify",
        }
        if name in {"search_hot_notes", "search_trending_topics", "analyze_hot_notes"}:
            providers = arguments.get("providers") or [None]
            for provider in providers:
                self._enterprise_authorize(
                    principal, "research.search", context={"search_provider": provider}
                )
            if arguments.get("web_results"):
                self._enterprise_authorize(
                    principal, "research.search", context={"search_provider": "client_web"}
                )
        elif name in operation_map:
            context: dict[str, Any] = {}
            if name == "generate_xhs_note":
                context["provider"] = arguments.get("provider")
            if name == "create_publish_draft":
                context["account_id"] = arguments.get("account_id")
            if name in {"publish_note", "schedule_note"}:
                draft = self.publishing.repository.load_draft(
                    arguments["draft_id"], principal.tenant_id
                )
                context["account_id"] = draft.account_id
            self._enterprise_authorize(principal, operation_map[name], context=context)
        if name in {"search_hot_notes", "search_trending_topics", "analyze_hot_notes"}:
            try:
                report = await self.research.search_hot_notes(
                    SearchQuery(
                        query=arguments["query"],
                        time_range=arguments.get("time_range", "7d"),
                        limit=arguments.get("limit", 30),
                    ),
                    providers=arguments.get("providers"),
                    web_results=arguments.get("web_results"),
                )
            except ClientWebSearchRequired as exc:
                return exc.to_payload()
            if name == "search_trending_topics":
                return {
                    "query": report.query,
                    "trends": [item.model_dump(mode="json") for item in report.trends],
                    "content_gaps": report.content_gaps,
                    "topic_suggestions": report.topic_suggestions
                    or suggest_topics_from_report(report),
                    "hot_insights": report.hot_insights,
                    "topic_heat": (report.hot_insights or {}).get("topic_heat", []),
                    "summary": (report.hot_insights or {}).get("summary"),
                    "coverage_warning": report.coverage_warning,
                }
            if name == "analyze_hot_notes":
                return {
                    "query": report.query,
                    "mechanisms": [item.model_dump(mode="json") for item in report.mechanisms],
                    "content_gaps": report.content_gaps,
                    "topic_suggestions": report.topic_suggestions
                    or suggest_topics_from_report(report),
                    "title_mechanism_stats": (report.hot_insights or {}).get(
                        "title_mechanism_stats", []
                    ),
                    "viral_candidates": (report.hot_insights or {}).get("viral_candidates", []),
                    "notes_analyzed": len(report.notes),
                    "coverage_warning": report.coverage_warning,
                }
            payload = report.model_dump(mode="json")
            if not payload.get("topic_suggestions"):
                payload["topic_suggestions"] = suggest_topics_from_report(report)
            return payload
        if name == "generate_xhs_note":
            try:
                package = await self.workflow.run(
                    GenerateRequest.model_validate(arguments),
                    tenant_id=principal.tenant_id,
                    web_results=arguments.get("web_results"),
                )
            except ClientWebSearchRequired as exc:
                return exc.to_payload()
            data = package.model_dump(mode="json")
            from xhs_skill.generation.creation_bundle import build_creation_bundle

            data["creation_bundle"] = build_creation_bundle(package)
            return data
        if name == "plan_content_outline":
            from xhs_skill.generation.outline import build_content_outline

            req = GenerateRequest.model_validate(
                {
                    "topic": arguments["topic"],
                    "target_audience": arguments.get("target_audience"),
                    "product": arguments.get("product") or {},
                    "constraints": arguments.get("constraints") or [],
                    "note_style": arguments.get("note_style"),
                    "narrative_framework": arguments.get("narrative_framework"),
                    "variant_index": int(arguments.get("variant_index") or 0),
                    "research_current_trends": False,
                }
            )
            return build_content_outline(
                req,
                None,
                note_style=req.note_style,
                narrative_framework=req.narrative_framework,
                variant_index=req.variant_index,
            )
        if name == "rewrite_xhs_note":
            body = str(arguments["body"])
            result = await self.workflow.generation.rewrite(
                body=body,
                title=str(arguments.get("title", "")),
                commercial_status=str(arguments.get("commercial_status", "NON_COMMERCIAL")),
                constraints=[str(c) for c in arguments.get("constraints", [])],
                references=[str(item) for item in arguments.get("references", [])],
                tenant_id=principal.tenant_id,
            )
            structure = structure_checks(
                title=str(result.get("title") or arguments.get("title") or ""),
                body=str(result.get("body") or body),
                cta=str(result.get("cta") or ""),
                pinned_comment=str(result.get("pinned_comment") or ""),
            )
            result["structure_checks"] = structure
            from xhs_skill.generation.creation_bundle import rewrite_title_and_hook

            result["title_hook"] = rewrite_title_and_hook(
                str(result.get("revised") or result.get("body") or body),
                str(arguments.get("title") or ""),
            )
            return result
        if name == "diagnose_xhs_note":
            title = str(arguments.get("title", ""))
            body = str(arguments["body"])
            refs = [str(item) for item in arguments.get("references", [])]
            allowed_images = {"image/jpeg", "image/png", "image/webp", "image/gif"}
            candidate_ids = [str(item) for item in arguments.get("candidate_image_asset_ids", [])]
            reference_ids = [str(item) for item in arguments.get("reference_image_asset_ids", [])]
            candidate_images = [
                str(
                    self.asset_store.resolve(
                        principal.tenant_id, asset_id, allowed_types=allowed_images
                    )
                )
                for asset_id in candidate_ids
            ]
            reference_images = [
                str(
                    self.asset_store.resolve(
                        principal.tenant_id, asset_id, allowed_types=allowed_images
                    )
                )
                for asset_id in reference_ids
            ]
            structure = structure_checks(title=title, body=body)
            return {
                "compliance": check_text(f"{title}\n{body}"),
                "originality": await originality_report_async(
                    body,
                    refs,
                    candidate_images=candidate_images,
                    reference_images=reference_images,
                    candidate_image_labels=candidate_ids,
                    reference_image_labels=reference_ids,
                ),
                "ai_style": ai_style_report(body),
                "structure_checks": structure,
                "recommended_fixes": structure["recommended_fixes"]
                or [
                    "增加具体场景、限制条件和不适合人群",
                    "删除无法验证的数据和效果承诺",
                ],
            }
        if name == "verify_claims":
            claims = extract_claims(str(arguments["text"]), arguments.get("evidence", []))
            return {"claims": [item.model_dump(mode="json") for item in claims]}
        if name == "check_originality":
            allowed_images = {"image/jpeg", "image/png", "image/webp", "image/gif"}
            candidate_images = [
                str(
                    self.asset_store.resolve(
                        principal.tenant_id, str(asset_id), allowed_types=allowed_images
                    )
                )
                for asset_id in arguments.get("candidate_image_asset_ids", [])
            ]
            reference_images = [
                str(
                    self.asset_store.resolve(
                        principal.tenant_id, str(asset_id), allowed_types=allowed_images
                    )
                )
                for asset_id in arguments.get("reference_image_asset_ids", [])
            ]
            return await originality_report_async(
                str(arguments["text"]),
                [str(item) for item in arguments.get("references", [])],
                candidate_images=candidate_images,
                reference_images=reference_images,
                candidate_image_labels=[
                    str(item) for item in arguments.get("candidate_image_asset_ids", [])
                ],
                reference_image_labels=[
                    str(item) for item in arguments.get("reference_image_asset_ids", [])
                ],
            )
        if name == "check_compliance":
            status = CommercialStatus(arguments.get("commercial_status", CommercialStatus.NON_COMMERCIAL))
            return check_text(str(arguments["text"]), status)
        if name == "query_account_weight":
            account_id = arguments["account_id"]
            analytics = arguments.get("analytics")
            data = AccountAnalytics(account_id=account_id, **analytics) if analytics else None
            return cast(
                dict[str, Any], self.accounts.query_weight(account_id, data, principal.tenant_id).model_dump(mode="json")
            )
        if name == "query_content_health":
            account_id = arguments["account_id"]
            analytics = arguments.get("analytics")
            data = AccountAnalytics(account_id=account_id, **analytics) if analytics else None
            return self.accounts.content_health(account_id, data, principal.tenant_id)
        if name == "diagnose_account":
            account_id = arguments["account_id"]
            analytics = arguments.get("analytics")
            data = AccountAnalytics(account_id=account_id, **analytics) if analytics else None
            return self.accounts.account_diagnosis(
                account_id,
                data,
                principal.tenant_id,
                base_topic=arguments.get("base_topic"),
            )
        if name == "suggest_topics_by_health":
            account_id = str(arguments["account_id"])
            analytics = arguments.get("analytics")
            data = AccountAnalytics(account_id=account_id, **analytics) if analytics else None
            research_suggestions = None
            query = str(arguments.get("query") or arguments.get("base_topic") or "").strip()
            if query:
                try:
                    report = await self.research.search_hot_notes(
                        SearchQuery(query=query, time_range="7d", limit=30),
                        providers=arguments.get("providers"),
                        web_results=arguments.get("web_results"),
                    )
                    research_suggestions = list(
                        report.topic_suggestions or suggest_topics_from_report(report)
                    )
                except ClientWebSearchRequired as exc:
                    return exc.to_payload()
            result = self.accounts.suggest_topics_from_health(
                account_id,
                analytics=data,
                base_topic=str(arguments["base_topic"])
                if arguments.get("base_topic")
                else (query or None),
                research_suggestions=research_suggestions,
                tenant_id=principal.tenant_id,
                limit=int(arguments.get("limit") or 8),
            )
            if research_suggestions is not None and query:
                result["query"] = query
            return result
        if name == "sync_account_analytics":
            account_id = arguments["account_id"]
            data = AccountAnalytics(account_id=account_id, **arguments["analytics"])
            return self.accounts.sync(data, principal.tenant_id).model_dump(mode="json")
        if name == "start_account_login":
            return (
                await self.login.start(arguments["account_id"], principal.tenant_id)
            ).model_dump(mode="json")
        if name == "check_account_login":
            return (
                await self.login.status(arguments["account_id"], principal.tenant_id)
            ).model_dump(mode="json")
        if name == "logout_account":
            self._require_approval(arguments)
            return (
                await self.login.logout(
                    arguments["account_id"],
                    tenant_id=principal.tenant_id,
                    delete_session=arguments.get("delete_session", True),
                )
            ).model_dump(mode="json")
        if name == "create_publish_draft":
            package = DeliveryPackage.model_validate(arguments["package"])
            mode = PublishMode(arguments.get("mode", PublishMode.REQUIRE_CONFIRMATION))
            return self.publishing.create_draft(
                arguments["account_id"],
                package,
                mode,
                tenant_id=principal.tenant_id,
                created_by=principal.subject,
            ).model_dump(mode="json")
        if name == "preview_publish_draft":
            return (
                await self.publishing.preview(
                    arguments["draft_id"], tenant_id=principal.tenant_id
                )
            ).model_dump(mode="json")
        if name == "approve_publish_draft":
            return self.publishing.approve(
                arguments["draft_id"],
                arguments.get("ttl_minutes", 30),
                tenant_id=principal.tenant_id,
                approved_by=principal.subject,
                approver_auth_level=principal.auth_level,
                ai_disclosure_confirmed=arguments.get("ai_disclosure_confirmed", False),
                commercial_disclosure_confirmed=arguments.get(
                    "commercial_disclosure_confirmed", False
                ),
                account_identity_confirmed=arguments.get("account_identity_confirmed", False),
                enterprise_approval_id=arguments.get("enterprise_approval_id"),
            ).model_dump(mode="json")
        if name == "publish_note":
            self._require_approval(arguments)
            return (
                await self.publishing.publish(
                    arguments["draft_id"],
                    arguments["approval_token"],
                    tenant_id=principal.tenant_id,
                )
            ).model_dump(mode="json")
        if name == "schedule_note":
            self._require_approval(arguments)
            scheduled_at = datetime.fromisoformat(arguments["scheduled_at"])
            return (await self.publishing.schedule(
                arguments["draft_id"],
                arguments["approval_token"],
                scheduled_at,
                tenant_id=principal.tenant_id,
            )).model_dump(mode="json")
        if name == "get_enterprise_controls":
            tenant = self.enterprise_repository.get_tenant(principal.tenant_id)
            return {
                "version": "5.12.0",
                "tenant": tenant.model_dump(mode="json"),
                "budget": self.enterprise_costs.summary(principal.tenant_id).model_dump(mode="json"),
                "audit": self.enterprise_audit.verify(principal.tenant_id).model_dump(mode="json"),
            }
        if name == "get_enterprise_budget":
            return self.enterprise_costs.summary(principal.tenant_id).model_dump(mode="json")
        if name == "create_enterprise_approval":
            return self.enterprise_approvals.create(
                principal=principal,
                resource_type=str(arguments["resource_type"]),
                resource_id=str(arguments["resource_id"]),
                content_hash=str(arguments.get("content_hash") or "") or None,
                ttl_minutes=int(arguments.get("ttl_minutes", 30)),
            ).model_dump(mode="json")
        if name == "decide_enterprise_approval":
            return self.enterprise_approvals.decide(
                str(arguments["approval_id"]),
                principal=principal,
                decision=str(arguments["decision"]),
                comment=str(arguments.get("comment", "")),
            ).model_dump(mode="json")
        if name == "verify_enterprise_audit":
            return self.enterprise_audit.verify(principal.tenant_id).model_dump(mode="json")
        if name == "enterprise_dlp_scan":
            text = str(arguments["text"])
            findings = scan_text(text)
            output, _ = redact_text(text) if arguments.get("redact", True) else (text, findings)
            return {
                "redacted_text": output,
                "findings": [item.__dict__ for item in findings],
                "blocking": any(item.severity == "CRITICAL" for item in findings),
            }
        if name == "sync_published_metrics":
            metrics = PublishedMetrics.model_validate(arguments["metrics"]).model_copy(
                update={"tenant_id": principal.tenant_id}
            )
            return (await self.operations.sync_published_metrics_async(metrics)).model_dump(mode="json")
        if name == "get_performance_attribution":
            return (
                await self.operations.performance_attribution_async(
                    tenant_id=principal.tenant_id,
                    account_id=str(arguments["account_id"]),
                    note_id=str(arguments["note_id"]),
                )
            ).model_dump(mode="json")
        if name == "get_account_weight_trend":
            return await self.operations.account_weight_trend_async(
                str(arguments["account_id"]), principal.tenant_id
            )
        if name == "create_content_calendar":
            raw_topics = arguments.get("topics") or []
            raw_fallback = arguments.get("fallback_topics") or []
            calendar_items = await self.operations.create_calendar_async(
                account_id=str(arguments["account_id"]),
                topics=[str(item) for item in raw_topics],
                tenant_id=principal.tenant_id,
                days=int(arguments.get("days", 30)),
                posts_per_week=int(arguments.get("posts_per_week", 3)),
                fallback_topics=[str(item) for item in raw_fallback] or None,
            )
            return {"items": [item.model_dump(mode="json") for item in calendar_items]}
        if name == "create_content_series":
            return (await self.operations.create_series_async(
                account_id=str(arguments["account_id"]),
                title=str(arguments["title"]),
                topic=str(arguments["topic"]),
                audience=str(arguments["audience"]),
                episode_count=int(arguments.get("episode_count", 6)),
                tenant_id=principal.tenant_id,
            )).model_dump(mode="json")
        if name == "create_abn_experiment":
            experiment = Experiment.model_validate(arguments["experiment"]).model_copy(
                update={"tenant_id": principal.tenant_id}
            )
            return (await self.operations.create_experiment_async(experiment)).model_dump(mode="json")
        if name == "assign_experiment_variant":
            return (
                await self.operations.assign_experiment_async(
                    principal.tenant_id,
                    str(arguments["experiment_id"]),
                    str(arguments["subject_id"]),
                )
            ).model_dump(mode="json")
        if name == "record_experiment_outcome":
            outcome = ExperimentOutcome.model_validate(arguments["outcome"])
            return (
                await self.operations.record_experiment_outcome_async(
                    principal.tenant_id, outcome
                )
            ).model_dump(mode="json")
        if name == "analyze_abn_experiment":
            return (
                await self.operations.analyze_experiment_async(
                    principal.tenant_id,
                    str(arguments["experiment_id"]),
                    minimum_samples_per_variant=int(
                        arguments.get("minimum_samples_per_variant", 20)
                    ),
                )
            ).model_dump(mode="json")
        if name == "choose_content_bandit":
            from xhs_skill.operations.bandit_context import describe_bandit_context

            raw_ctx = arguments.get("context")
            decision = await self.operations.choose_bandit_async(
                tenant_id=principal.tenant_id,
                policy_id=str(arguments["policy_id"]),
                subject_id=str(arguments["subject_id"]),
                arms=[str(item) for item in arguments["arms"]],
                context=[float(item) for item in raw_ctx] if raw_ctx else None,
                features=arguments.get("features")
                if isinstance(arguments.get("features"), dict)
                else None,
                account_id=str(arguments["account_id"])
                if arguments.get("account_id")
                else None,
                auto_account_weight=bool(arguments.get("auto_account_weight", True)),
            )
            payload = decision.model_dump(mode="json")
            payload["context_features"] = describe_bandit_context(decision.context)
            return payload
        if name == "update_content_bandit":
            raw_ctx = arguments.get("context")
            await self.operations.update_bandit_async(
                tenant_id=principal.tenant_id,
                policy_id=str(arguments["policy_id"]),
                arm_id=str(arguments["arm_id"]),
                context=[float(item) for item in raw_ctx] if raw_ctx else None,
                features=arguments.get("features")
                if isinstance(arguments.get("features"), dict)
                else None,
                account_id=str(arguments["account_id"])
                if arguments.get("account_id")
                else None,
                auto_account_weight=bool(arguments.get("auto_account_weight", True)),
                reward=float(arguments["reward"]),
            )
            return {"updated": True}
        if name == "search_asset_library":
            asset_items = await self.operations.search_assets_async(
                principal.tenant_id,
                [str(item) for item in arguments.get("tags", [])] or None,
            )
            return {
                "items": [
                    item.model_dump(mode="json", exclude={"storage_path"})
                    for item in asset_items
                ]
            }
        if name == "generate_retrospective":
            data = await self.operations.retrospective_enriched_async(
                principal.tenant_id,
                str(arguments["account_id"]),
                str(arguments["note_id"]),
            )
            return data
        if name == "list_job_dead_letters":
            return {"items": await RedisDeadLetterQueue().list(count=int(arguments.get("count", 100)))}
        if name == "replay_job_dead_letter":
            self._require_approval(arguments)
            return {"replayed_as": await RedisDeadLetterQueue().replay(str(arguments["message_id"]))}
        if name == "analyze_performance":
            metric_values = dict(arguments["metrics"])
            positives = [key for key, value in metric_values.items() if isinstance(value, (int, float)) and value > 0]
            return {
                "metrics": metric_values,
                "observed_positive_signals": positives,
                "caveat": "这是描述性复盘；没有随机实验时不能作确定因果判断。",
                "next_experiments": ["单变量测试标题", "单变量测试封面", "比较搜索版与推荐版"],
            }
        if name == "draft_comment_reply":
            from xhs_skill.generation.reply_draft import (
                build_authorized_reply_drafts,
                reply_draft_to_dict,
            )

            draft = build_authorized_reply_drafts(
                str(arguments["original_comment"]),
                note_context=str(arguments.get("note_context") or ""),
                tone=str(arguments.get("tone") or "helpful"),
                comment_id=str(arguments["comment_id"]) if arguments.get("comment_id") else None,
                note_id=str(arguments["note_id"]) if arguments.get("note_id") else None,
                max_candidates=int(arguments.get("max_candidates") or 3),
            )
            return reply_draft_to_dict(draft)
        if name == "generate_xhs_note_variants":
            req = GenerateRequest.model_validate(
                {k: v for k, v in arguments.items() if k != "variant_count"}
            )
            report = None
            if req.research_current_trends:
                try:
                    report = await self.research.search_hot_notes(
                        SearchQuery(query=req.topic, limit=20),
                        web_results=arguments.get("web_results"),
                    )
                except ClientWebSearchRequired as exc:
                    return exc.to_payload()
            return await self.workflow.generation.generate_variants(
                req,
                report,
                tenant_id=principal.tenant_id,
                variant_count=int(arguments.get("variant_count") or 3),
            )
        if name == "generate_from_hot":
            from xhs_skill.orchestrator.hot_to_note import run_hot_to_note
            from xhs_skill.search.adaptive import ClientWebSearchRequired as _CWR

            try:
                return await run_hot_to_note(
                    self.workflow,
                    query=str(arguments["query"]),
                    suggestion_index=int(arguments.get("suggestion_index") or 0),
                    suggestion_topic=str(arguments["suggestion_topic"])
                    if arguments.get("suggestion_topic")
                    else None,
                    dry_run=bool(arguments.get("dry_run", False)),
                    providers=arguments.get("providers"),
                    web_results=arguments.get("web_results"),
                    tenant_id=principal.tenant_id,
                    format=str(arguments.get("format") or "graphic"),
                    video_duration_seconds=int(arguments["video_duration_seconds"])
                    if arguments.get("video_duration_seconds") is not None
                    else None,
                    account_id=str(arguments["account_id"]) if arguments.get("account_id") else None,
                    use_account_health=bool(arguments.get("use_account_health", False)),
                    target_audience=str(arguments["target_audience"])
                    if arguments.get("target_audience")
                    else None,
                    commercial_status=str(arguments["commercial_status"])
                    if arguments.get("commercial_status")
                    else None,
                    brand_voice=arguments.get("brand_voice")
                    if isinstance(arguments.get("brand_voice"), dict)
                    else None,
                    product=arguments.get("product")
                    if isinstance(arguments.get("product"), dict)
                    else None,
                    constraints=[str(c) for c in arguments.get("constraints", [])] or None,
                    note_style=str(arguments["note_style"]) if arguments.get("note_style") else None,
                    narrative_framework=str(arguments["narrative_framework"])
                    if arguments.get("narrative_framework")
                    else None,
                    provider=str(arguments["provider"]) if arguments.get("provider") else None,
                    accounts_service=self.accounts,
                )
            except _CWR as exc:
                return exc.to_payload()
            except ValueError as exc:
                return {"status": "error", "error": str(exc)}
        if name == "get_publish_windows":
            from xhs_skill.operations.publish_timing import best_publish_windows

            profile = await self.accounts.profile_async(
                str(arguments["account_id"]), principal.tenant_id
            )
            return best_publish_windows(profile)
        raise KeyError(f"Unknown tool {name}")
