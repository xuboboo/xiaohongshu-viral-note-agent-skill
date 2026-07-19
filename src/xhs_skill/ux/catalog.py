"""工具场景分组：给 Agent 在 tools/list 里快速扫工具。"""

from __future__ import annotations

from typing import Any

# 稳定分组 id → 中文标签
TOOL_GROUP_LABELS: dict[str, str] = {
    "research": "研究/选题",
    "generate": "生成/改写",
    "verify": "校验门禁",
    "account": "账号/登录",
    "publish": "发布流",
    "operations": "发后运营",
    "enterprise": "企业管控",
    "jobs": "任务运维",
}

# tool name → group
TOOL_GROUPS: dict[str, str] = {
    "search_hot_notes": "research",
    "search_trending_topics": "research",
    "analyze_hot_notes": "research",
    "suggest_topics_by_health": "research",
    "generate_from_hot": "generate",
    "generate_xhs_note": "generate",
    "generate_xhs_note_variants": "generate",
    "plan_content_outline": "generate",
    "rewrite_xhs_note": "generate",
    "diagnose_xhs_note": "generate",
    "draft_comment_reply": "generate",
    "verify_claims": "verify",
    "check_originality": "verify",
    "check_compliance": "verify",
    "query_account_weight": "account",
    "query_content_health": "account",
    "diagnose_account": "account",
    "sync_account_analytics": "account",
    "start_account_login": "account",
    "check_account_login": "account",
    "logout_account": "account",
    "create_publish_draft": "publish",
    "preview_publish_draft": "publish",
    "approve_publish_draft": "publish",
    "publish_note": "publish",
    "schedule_note": "publish",
    "get_publish_windows": "publish",
    "sync_published_metrics": "operations",
    "get_performance_attribution": "operations",
    "get_account_weight_trend": "operations",
    "create_content_calendar": "operations",
    "create_content_series": "operations",
    "create_abn_experiment": "operations",
    "assign_experiment_variant": "operations",
    "record_experiment_outcome": "operations",
    "analyze_abn_experiment": "operations",
    "choose_content_bandit": "operations",
    "update_content_bandit": "operations",
    "search_asset_library": "operations",
    "generate_retrospective": "operations",
    "analyze_performance": "operations",
    "get_enterprise_controls": "enterprise",
    "get_enterprise_budget": "enterprise",
    "create_enterprise_approval": "enterprise",
    "decide_enterprise_approval": "enterprise",
    "verify_enterprise_audit": "enterprise",
    "enterprise_dlp_scan": "enterprise",
    "list_job_dead_letters": "jobs",
    "replay_job_dead_letter": "jobs",
    # CLI-only aliases mapped for enrich_tool_result / 文档
    "doctor": "jobs",
    "publish_canary": "publish",
}


def group_for(tool_name: str) -> str:
    return TOOL_GROUPS.get(tool_name, "general")


def label_for(group: str) -> str:
    return TOOL_GROUP_LABELS.get(group, group)


def prefix_description(tool_name: str, description: str) -> str:
    """描述前缀，兼容只读 description 的宿主。"""
    group = group_for(tool_name)
    label = label_for(group)
    tag = f"[{label}] "
    if description.startswith("["):
        return description
    return tag + description


def annotate_tool_definition(tool: dict[str, Any]) -> dict[str, Any]:
    """给 tools/list 条目加 category 元数据 + 描述前缀。"""
    out = dict(tool)
    name = str(out.get("name") or "")
    group = group_for(name)
    desc = str(out.get("description") or "")
    out["description"] = prefix_description(name, desc)
    meta = dict(out.get("_meta") or {})
    meta["category"] = group
    meta["category_label"] = label_for(group)
    out["_meta"] = meta
    # 部分宿主读 annotations
    annotations = dict(out.get("annotations") or {})
    annotations.setdefault("category", group)
    out["annotations"] = annotations
    return out


def tools_list_meta(tool_names: list[str] | None = None) -> dict[str, Any]:
    """tools/list 附带的分组索引。"""
    names = tool_names if tool_names is not None else list(TOOL_GROUPS.keys())
    by_group: dict[str, list[str]] = {}
    for name in names:
        g = group_for(name)
        by_group.setdefault(g, []).append(name)
    return {
        "schema": "tool_groups.v1",
        "groups": [
            {
                "id": gid,
                "label": label_for(gid),
                "tools": sorted(tools),
            }
            for gid, tools in sorted(by_group.items(), key=lambda x: label_for(x[0]))
        ],
        "read_order": [
            "ux.status → ux.summary → ux.next_step → 业务字段",
            "黄金路径: research → generate → verify → publish → operations",
        ],
    }