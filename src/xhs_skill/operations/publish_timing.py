"""发后运营辅助：最佳发布时间提示、复盘→生成/日历载荷。"""

from __future__ import annotations

from typing import Any

from xhs_skill.schemas.account import AccountProfile


def best_publish_windows(profile: AccountProfile | None = None) -> dict[str, Any]:
    """从画像给出发帖窗口建议（启发式，非官方流量秘密）。"""
    days = (
        list(profile.optimal_publish_days)
        if profile and profile.optimal_publish_days
        else [1, 3, 6]
    )
    hours = (
        list(profile.optimal_publish_hours)
        if profile and profile.optimal_publish_hours
        else [12, 18, 20, 21]
    )
    day_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return {
        "weekday_indices": days,
        "weekday_labels": [day_names[i] for i in days if 0 <= i <= 6],
        "hours_local": hours,
        "suggestion": (
            f"优先在 {', '.join(day_names[i] for i in days if 0 <= i <= 6)} "
            f"的 {', '.join(str(h) + ':00' for h in hours[:3])} 附近发布；"
            "以你账号历史数据为准，本建议仅作排期起点。"
        ),
        "source": "account_profile_or_default",
    }


def generate_request_from_suggestion(suggestion: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """把 next_note_suggestions / topic_suggestions 项转成 generate_xhs_note 参数。"""
    topic = str(suggestion.get("topic") or overrides.get("topic") or "").strip()
    payload = {
        "topic": topic,
        "suggested_topic": topic,
        "topic_angle": str(suggestion.get("angle") or "")[:120] or None,
        "topic_reason": str(suggestion.get("reason") or "")[:400] or None,
        "objective": "search_growth",
        "format": "graphic",
        "research_current_trends": True,
    }
    payload.update({k: v for k, v in overrides.items() if v is not None})
    return {k: v for k, v in payload.items() if v is not None}


def calendar_topics_from_retrospective(retrospective: dict[str, Any]) -> list[str]:
    topics: list[str] = []
    for item in retrospective.get("next_note_suggestions") or []:
        if isinstance(item, dict) and item.get("topic"):
            topics.append(str(item["topic"])[:80])
    for action in retrospective.get("next_actions") or []:
        text = str(action).strip()
        if text and len(text) <= 40:
            topics.append(text)
    # 去重
    seen: set[str] = set()
    out: list[str] = []
    for t in topics:
        key = t.casefold()
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out[:12]