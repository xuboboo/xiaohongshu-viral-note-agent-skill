"""热门洞察：在公开索引/授权指标排序之上，给出爆款标签与话题热度解读。"""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Any

from xhs_skill.core.title_mechanisms import tag_title_mechanisms
from xhs_skill.schemas.research import HotNoteCandidate, ScoreType, TrendClass, TrendTopic

# 绝对分门槛（与分位双条件）
_ABS_VIRAL = 75.0
_ABS_HIGH = 55.0
_ABS_MID = 35.0


def _percentile_rank(score: float, scores: list[float]) -> float:
    if not scores:
        return 0.0
    if len(scores) == 1:
        return 1.0
    below = sum(1 for item in scores if item < score)
    equal = sum(1 for item in scores if item == score)
    # 中位秩：同名次取半
    return round((below + 0.5 * equal) / len(scores), 4)


def _heat_band(score: float, percentile: float) -> str:
    """分位 + 绝对分双条件，避免小样本全员「爆款」。"""
    if score >= _ABS_VIRAL and percentile >= 0.90:
        return "爆款候选"
    if score >= _ABS_HIGH and percentile >= 0.70:
        return "高热"
    if score >= _ABS_MID and percentile >= 0.40:
        return "中热"
    # 绝对分很高但样本分位不足时，仍给高热而非假爆款
    if score >= _ABS_VIRAL:
        return "高热"
    if score >= _ABS_HIGH:
        return "中热"
    return "长尾"


def _relative_to_query(score: float, scores: list[float]) -> str:
    if not scores:
        return "unknown"
    mean = statistics.fmean(scores)
    if score >= mean * 1.25:
        return "above_query_mean"
    if score <= mean * 0.75:
        return "below_query_mean"
    return "near_query_mean"


def label_note_heat(
    note: HotNoteCandidate,
    *,
    rank: int,
    score_type: ScoreType,
    all_scores: list[float] | None = None,
) -> dict[str, Any]:
    score = float(note.hot_score or 0)
    pool = list(all_scores) if all_scores is not None else [score]
    percentile = _percentile_rank(score, pool)
    band = _heat_band(score, percentile)
    tags = tag_title_mechanisms(note.title)
    why: list[str] = []
    comps = note.score_components or {}
    if comps.get("freshness", 0) >= 0.15 or comps.get("freshness", 0) >= 0.5:
        why.append("时效较新")
    if comps.get("engagement") or comps.get("velocity"):
        why.append("互动/速度信号")
    if comps.get("relevance", 0) >= 0.5:
        why.append("与查询相关")
    if comps.get("search_rank") or comps.get("cross_engine_support"):
        why.append("公开索引可见度")
    if tags:
        why.append("标题机制：" + "、".join(tags[:2]))
    if percentile >= 0.9:
        why.append(f"样本内分位 P{int(percentile * 100)}")
    return {
        "rank": rank,
        "note_id": note.id,
        "title": note.title,
        "url": note.url,
        "hot_score": score,
        "percentile": percentile,
        "relative_to_query": _relative_to_query(score, pool),
        "heat_band": band,
        "title_mechanisms": tags,
        "why_hot": why[:5] or ["综合排序靠前"],
        "score_type": score_type.value if hasattr(score_type, "value") else str(score_type),
        "likes": note.likes,
        "saves": note.saves,
        "comments": note.comments,
    }


def _stage_confidence(trend: TrendTopic) -> float:
    """阶段置信：多信号一致时更高。"""
    conf = 0.45
    if trend.change_point_detected:
        conf += 0.15
    if abs(trend.growth_rate) >= 0.35:
        conf += 0.12
    if trend.cross_source_support >= 0.4:
        conf += 0.1
    if trend.evidence_note_ids and len(trend.evidence_note_ids) >= 3:
        conf += 0.1
    if trend.saturation >= 0.75 or trend.saturation <= 0.25:
        conf += 0.05
    return round(min(0.95, conf), 3)


def topic_heat_cards(trends: list[TrendTopic], *, limit: int = 8) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for trend in trends[:limit]:
        stage = str(trend.trend_class)
        if stage in {TrendClass.RISING, TrendClass.EMERGING, "RISING", "EMERGING"}:
            action = "可跟进，优先长尾场景与反例"
        elif stage in {TrendClass.SATURATED, "SATURATED"}:
            action = "红海，需差异化角度"
        elif stage in {TrendClass.DECLINING, "DECLINING"}:
            action = "谨慎追，除非有新证据"
        elif stage in {TrendClass.ANOMALOUS, "ANOMALOUS"}:
            action = "异常波动，先核验样本再跟"
        elif stage in {TrendClass.SEASONAL, "SEASONAL"}:
            action = "季节性话题，卡窗口做常青变体"
        else:
            action = "可观察，结合自身账号定位"
        # 生命周期阶段别名（产品面）
        lifecycle = {
            "EMERGING": "萌发",
            "RISING": "上升",
            "STABLE": "平稳",
            "SEASONAL": "季节",
            "SATURATED": "高峰饱和",
            "DECLINING": "衰退",
            "ANOMALOUS": "异常",
        }.get(stage.replace("TrendClass.", ""), stage)
        cards.append(
            {
                "topic": trend.topic,
                "trend_class": stage,
                "lifecycle_stage": lifecycle,
                "stage_confidence": _stage_confidence(trend),
                "score": trend.score,
                "growth_rate": trend.growth_rate,
                "saturation": trend.saturation,
                "gap_score": trend.content_gap_score,
                "action_hint": action,
                "evidence_note_ids": list(trend.evidence_note_ids or [])[:5],
            }
        )
    return cards


def mechanism_frequency(notes: list[HotNoteCandidate], *, limit: int = 6) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for note in notes:
        for tag in tag_title_mechanisms(note.title):
            counter[tag] += 1
    total = max(sum(counter.values()), 1)
    return [
        {"mechanism": name, "count": count, "share": round(count / total, 3)}
        for name, count in counter.most_common(limit)
    ]


def content_gap_cards(gaps: list[dict[str, Any]] | None, *, limit: int = 6) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for gap in (gaps or [])[:limit]:
        if not isinstance(gap, dict):
            continue
        term = str(gap.get("gap") or "").strip()
        if not term:
            continue
        cards.append(
            {
                "gap": term,
                "gap_score": round(float(gap.get("gap_score") or 0), 4),
                "coverage_ratio": gap.get("coverage_ratio"),
                "recommendation": str(gap.get("recommendation") or "")[:200],
                "action_hint": "补具体场景、评价标准与不适合人群",
            }
        )
    return cards


def build_hot_insights(
    notes: list[HotNoteCandidate],
    trends: list[TrendTopic],
    *,
    query: str,
    score_type: ScoreType,
    content_gaps: list[dict[str, Any]] | None = None,
    trend_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """爆款笔记解读 + 热门话题卡片（非官方热榜）。"""
    scores = [float(n.hot_score or 0) for n in notes[:30]]
    top = [
        label_note_heat(note, rank=i + 1, score_type=score_type, all_scores=scores)
        for i, note in enumerate(notes[:10])
    ]
    gap_cards = content_gap_cards(content_gaps)
    memory_block = trend_memory or {}
    comparison = memory_block.get("comparison") or {}
    from xhs_skill.research.early_signal import early_viral_signals

    early = early_viral_signals(notes)
    from xhs_skill.research.distiller import distill_search_playbook

    playbook = distill_search_playbook(notes, query)
    return {
        "query": query,
        "score_type": score_type.value if hasattr(score_type, "value") else str(score_type),
        "disclaimer": "公开索引/授权数据估算，不是小红书站内官方热榜。",
        "top_notes": top,
        "viral_candidates": [item for item in top if item["heat_band"] in {"爆款候选", "高热"}][:5],
        "early_signals": early,
        "topic_heat": topic_heat_cards(trends),
        "content_gaps": gap_cards,
        "title_mechanism_stats": mechanism_frequency(notes),
        "search_playbook": playbook,
        "keyword_matrix": playbook.get("keyword_matrix") or {},
        "query_intent": (playbook.get("query_intent") or {}).get("primary")
        if isinstance(playbook.get("query_intent"), dict)
        else playbook.get("query_intent"),
        "rising_words": comparison.get("rising_words") or [],
        "dual_axis": comparison.get("dual_axis") or [],
        "trend_memory": memory_block,
        "summary": _summary_line(top, trends, query, comparison=comparison, playbook=playbook),
    }


def _summary_line(
    top: list[dict[str, Any]],
    trends: list[TrendTopic],
    query: str,
    *,
    comparison: dict[str, Any] | None = None,
    playbook: dict[str, Any] | None = None,
) -> str:
    if not top:
        return f"「{query}」暂无足够样本，建议换词或补充 web_results。"
    bands = Counter(item["heat_band"] for item in top)
    rising = sum(
        1
        for t in trends
        if "RISING" in str(t.trend_class) or "EMERGING" in str(t.trend_class)
    )
    mem = ""
    if comparison and comparison.get("has_baseline"):
        n_rise = len(comparison.get("rising_words") or [])
        delta = comparison.get("mean_score_delta")
        mem = f" 相对上次摘要：上升词 {n_rise} 个"
        if delta is not None:
            mem += f"，均分Δ={delta}"
        mem += "。"
    intent_part = ""
    if playbook:
        qi = playbook.get("query_intent") or {}
        primary = qi.get("primary") if isinstance(qi, dict) else None
        mix = playbook.get("title_mechanism_mix") or []
        top_mech = mix[0]["mechanism"] if mix and isinstance(mix[0], dict) else None
        if primary or top_mech:
            intent_part = f" 主意图={primary or 'decision'}"
            if top_mech:
                intent_part += f"，样本高频机制「{top_mech}」"
            intent_part += "。"
    return (
        f"「{query}」样本 {len(top)} 条："
        f"{bands.get('爆款候选', 0)} 爆款候选 / {bands.get('高热', 0)} 高热；"
        f"上升/新兴话题约 {rising} 个。{mem}{intent_part}请结合账号定位再选题。"
    )