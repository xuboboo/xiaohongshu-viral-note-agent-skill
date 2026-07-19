"""搜索结果质量评估：用于缓存策略、自适应扩词与生成边界。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from xhs_skill.schemas.research import HotNoteCandidate, ScoreType


def assess_search_quality(
    notes: list[HotNoteCandidate],
    *,
    score_type: ScoreType,
    query: str,
    failures: int = 0,
    total_calls: int = 1,
) -> dict[str, Any]:
    """评估本次搜索质量（0–100），用于调整 TTL 和结果侧引导。"""
    n = len(notes)
    if n == 0:
        return {
            "score": 0,
            "label": "empty",
            "recommendations": ["换 query 或补充 web_results"],
            "cache_ttl_multiplier": 0.2,
        }

    now = datetime.now(UTC)

    sources = set(note.source_provider for note in notes)
    diversity = min(1.0, len(sources) / max(n, 1) * 2.5)

    fresh_count = 0
    for note in notes[:30]:
        age_h = (
            (now - (note.published_at or note.indexed_at or now)).total_seconds() / 3600
            if note.published_at or note.indexed_at
            else 9999
        )
        if age_h <= 72:
            fresh_count += 1
    freshness = fresh_count / max(min(n, 30), 1)

    has_title = sum(1 for note in notes[:30] if (note.title or "").strip())
    relevance = has_title / max(min(n, 30), 1)

    with_metrics = sum(
        1
        for note in notes[:30]
        if any(v is not None for v in (note.likes, note.saves, note.comments))
    )
    metric_coverage = with_metrics / max(min(n, 30), 1)

    failure_rate = failures / max(total_calls, 1)

    score = (
        diversity * 20
        + freshness * 30
        + relevance * 25
        + metric_coverage * 15
        + (1 - failure_rate) * 10
    )
    score = round(max(0.0, min(100.0, score)), 1)

    recommendations: list[str] = []
    if diversity < 0.4:
        recommendations.append("结果来源单一，可换 provider 或补 web_results")
    if freshness < 0.3:
        recommendations.append("结果偏旧，可缩短 time_range 或换词重搜")
    if metric_coverage < 0.2:
        recommendations.append("互动数据缺失，排序仅基于索引位置")
    if failure_rate > 0.3:
        recommendations.append(f"部分分片失败（{failures}/{total_calls}），可重试")

    if score >= 70:
        label = "good"
    elif score >= 40:
        label = "fair"
    else:
        label = "poor"

    multiplier = 1.0 if label == "good" else (0.5 if label == "fair" else 0.2)

    return {
        "score": score,
        "label": label,
        "metrics": {
            "source_diversity": round(diversity, 3),
            "freshness_72h": round(freshness, 3),
            "title_coverage": round(relevance, 3),
            "metric_coverage": round(metric_coverage, 3),
            "failure_rate": round(failure_rate, 3),
            "unique_sources": sorted(sources),
        },
        "recommendations": recommendations,
        "cache_ttl_multiplier": multiplier,
    }


def generation_guards_from_quality(quality: dict[str, Any] | None) -> dict[str, Any]:
    """低质量研究样本 → 生成侧硬约束与 assumption。"""
    quality = quality or {}
    score = float(quality.get("score") if quality.get("score") is not None else 50)
    label = str(quality.get("label") or "fair")
    recs = [str(r) for r in (quality.get("recommendations") or [])[:4]]

    if label in {"poor", "empty"} or score < 40:
        strength = "hard"
        constraints = [
            "evidence_boundary:研究样本质量偏低，禁止编造互动数据/排名/亲测功效",
            "disclaimer:正文须标明公开索引线索、非站内官方热榜",
            "tone:克制可核对，多用边界与不适合人群",
            "claims:客观说法必须可核验或改为主观表述",
        ]
        assumptions = [
            f"研究样本质量偏低（score={score:.0f}/{label}），成稿仅基于有限公开索引线索。",
            "不得把 PUBLIC_INDEX_TREND 表述为站内官方热榜或官方推荐。",
        ]
        if recs:
            assumptions.append("样本问题提示：" + "；".join(recs[:2]))
        disclaimer = "样本质量偏低：成稿加强边界与免责声明，禁止编造数据。"
    elif label == "fair" or score < 70:
        strength = "soft"
        constraints = [
            "evidence_boundary:互动/排名若未在样本中出现则不写具体数字",
            "disclaimer:公开索引线索，非官方热榜",
        ]
        assumptions = [
            f"研究样本质量一般（score={score:.0f}/{label}），关键事实需人工复核。",
        ]
        disclaimer = "样本质量一般：避免编造未出现的互动数字。"
    else:
        strength = "none"
        constraints = []
        assumptions = []
        disclaimer = ""

    return {
        "strength": strength,
        "constraints": constraints,
        "assumptions": assumptions,
        "disclaimer": disclaimer,
        "score": score,
        "label": label,
    }