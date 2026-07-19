"""话题/标签：相关度 vs 竞争度权衡（公开索引信号，非官方热词）。"""

from __future__ import annotations

from typing import Any

from xhs_skill.schemas.research import HotNotesReport, TrendClass


def balance_tags(
    topics: list[str],
    report: HotNotesReport | None,
    *,
    limit: int = 8,
) -> dict[str, Any]:
    """给标签打相关/竞争分并重排。"""
    if not topics:
        return {
            "topics": [],
            "hashtags": [],
            "scored": [],
            "disclaimer": "无标签可排序。",
        }

    trend_map = {}
    if report:
        for t in report.trends:
            trend_map[t.topic.casefold()] = t

    query = (report.query if report else "") or ""
    scored: list[dict[str, Any]] = []
    for tag in topics:
        key = tag.casefold()
        trend = trend_map.get(key)
        # 相关：与 query 重叠 / 在 trends 中
        rel = 0.35
        if query and (tag in query or query in tag):
            rel = 1.0
        elif trend:
            rel = 0.75
        elif any(ch in tag for ch in query[:4] if query):
            rel = 0.55

        # 竞争：饱和度或 SATURATED 类
        competition = 0.4
        opportunity = 0.5
        if trend:
            competition = float(trend.saturation or 0.4)
            if trend.trend_class in {TrendClass.SATURATED, "SATURATED"}:
                competition = max(competition, 0.8)
            if trend.trend_class in {TrendClass.RISING, TrendClass.EMERGING, "RISING", "EMERGING"}:
                opportunity = 0.85
            opportunity = max(opportunity, float(trend.content_gap_score or 0.4))

        # 综合：高相关 + 中低竞争
        balance = round(0.55 * rel + 0.45 * (1.0 - competition) * opportunity, 4)
        scored.append(
            {
                "tag": tag,
                "relevance": round(rel, 3),
                "competition": round(competition, 3),
                "opportunity": round(opportunity, 3),
                "balance_score": balance,
            }
        )

    scored.sort(key=lambda r: r["balance_score"], reverse=True)
    ordered = [r["tag"] for r in scored[:limit]]
    return {
        "topics": ordered,
        "hashtags": [f"#{t}" for t in ordered],
        "scored": scored[:limit],
        "disclaimer": "标签权衡来自公开索引趋势信号，不是官方热搜词。",
    }