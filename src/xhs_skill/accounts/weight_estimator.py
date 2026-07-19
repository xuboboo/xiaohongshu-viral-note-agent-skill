from __future__ import annotations

import math
import statistics
from collections.abc import Iterable

from xhs_skill.schemas.account import AccountAnalytics, AccountWeightReport, DimensionScore

WEIGHTS = {
    "account_health": 0.20,
    "content_quality_stability": 0.18,
    "interaction_efficiency": 0.17,
    "save_share_value": 0.12,
    "search_discovery": 0.10,
    "follower_growth_health": 0.08,
    "publishing_stability": 0.07,
    "content_verticality": 0.05,
    "risk_and_violations": 0.03,
}


def _bounded(value: float) -> float:
    return max(0.0, min(100.0, value))


def _ratio_score(numerator: int | None, denominator: int | None, target: float) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    # Bayesian smoothing with a small neutral prior.
    rate = (numerator + target * 200) / (denominator + 200)
    return _bounded(100 * rate / max(target, 1e-6))


def _evidence_score(items: Iterable[float | None], fallback: float = 50.0) -> float:
    valid = [item for item in items if item is not None]
    return round(statistics.fmean(valid), 2) if valid else fallback


def data_completeness(data: AccountAnalytics) -> tuple[float, list[str]]:
    fields = [
        "followers",
        "published_note_count",
        "recent_publish_count_30d",
        "views_30d",
        "likes_30d",
        "saves_30d",
        "comments_30d",
        "shares_30d",
        "follows_gained_30d",
        "profile_visits_30d",
        "search_views_30d",
        "recommendation_views_30d",
        "commercial_note_ratio",
        "deleted_note_count_90d",
        "violation_count_90d",
    ]
    missing = [field for field in fields if getattr(data, field) is None]
    return round((len(fields) - len(missing)) / len(fields), 4), missing


def estimate_account_weight(data: AccountAnalytics) -> AccountWeightReport:
    completeness, missing = data_completeness(data)
    if completeness < 0.4:
        return AccountWeightReport(
            overall_score=None,
            confidence="LOW",
            data_completeness=completeness,
            status="INSUFFICIENT_DATA",
            missing_data=missing,
            recommended_actions=["同步创作中心近 90 天数据后重新计算。"],
        )

    views = data.views_30d
    weighted = None
    if views:
        weighted_count = (
            0.15 * (data.likes_30d or 0)
            + 0.35 * (data.saves_30d or 0)
            + 0.20 * (data.comments_30d or 0)
            + 0.30 * (data.shares_30d or 0)
        )
        weighted = _bounded(100 * ((weighted_count + 8) / (views + 200)) / 0.04)

    account_health = (
        _bounded(92 - 12 * data.violation_count_90d - 2 * data.deleted_note_count_90d)
        if data.violation_count_90d is not None and data.deleted_note_count_90d is not None
        else 50.0
    )
    interaction = weighted if weighted is not None else 50.0
    save_rate = _ratio_score(data.saves_30d, views, 0.02)
    share_rate = _ratio_score(data.shares_30d, views, 0.008)
    save_share = _evidence_score([save_rate, share_rate])
    search_value = _ratio_score(data.search_views_30d, views, 0.20)
    follow_value = _ratio_score(data.follows_gained_30d, data.profile_visits_30d, 0.08)
    search = 50.0 if search_value is None else search_value
    follow = 50.0 if follow_value is None else follow_value

    count = data.recent_publish_count_30d or 0
    publishing_stability = _bounded(100 - abs(count - 12) * 5) if count else 35.0

    category_values = list(data.category_distribution.values())
    verticality = _bounded(max(category_values, default=0.5) * 100)

    performance_scores = []
    for note in data.note_performance:
        score = note.get("normalized_score")
        age_days = note.get("age_days", 0)
        if score is not None:
            performance_scores.append(float(score) * math.exp(-float(age_days) / 45))
    if performance_scores:
        median = statistics.median(performance_scores)
        spread = statistics.pstdev(performance_scores) if len(performance_scores) > 1 else 0
        quality_stability = _bounded(median - spread * 0.2)
    else:
        quality_stability = _evidence_score([interaction, save_share])

    risk_score = (
        _bounded(100 - 30 * data.violation_count_90d - 5 * data.deleted_note_count_90d)
        if data.violation_count_90d is not None and data.deleted_note_count_90d is not None
        else 50.0
    )

    raw = {
        "account_health": account_health,
        "content_quality_stability": quality_stability,
        "interaction_efficiency": interaction,
        "save_share_value": save_share,
        "search_discovery": search,
        "follower_growth_health": follow,
        "publishing_stability": publishing_stability,
        "content_verticality": verticality,
        "risk_and_violations": risk_score,
    }
    evidence_map: dict[str, list[str]] = {
        "account_health": (
            [
                f"violation_count_90d={data.violation_count_90d}",
                f"deleted_note_count_90d={data.deleted_note_count_90d}",
            ]
            if data.violation_count_90d is not None and data.deleted_note_count_90d is not None
            else ["违规/删除字段缺失，中性分 50"]
        ),
        "content_quality_stability": (
            [f"note_performance_n={len(performance_scores)}", f"decayed_median≈{statistics.median(performance_scores):.1f}"]
            if performance_scores
            else ["note_performance 不足，回退互动/收藏代理"]
        ),
        "interaction_efficiency": (
            [f"views_30d={views}", f"weighted_interaction_score={interaction:.1f}"]
            if views
            else ["views_30d 缺失"]
        ),
        "save_share_value": [
            f"saves_30d={data.saves_30d}",
            f"shares_30d={data.shares_30d}",
            "bayesian_smoothed_rates" if save_rate is not None else "rate_unavailable",
        ],
        "search_discovery": (
            [f"search_views_30d={data.search_views_30d}", f"score={search:.1f}"]
            if search_value is not None
            else ["search_views 缺失，中性 50"]
        ),
        "follower_growth_health": (
            [
                f"follows_gained_30d={data.follows_gained_30d}",
                f"profile_visits_30d={data.profile_visits_30d}",
            ]
            if follow_value is not None
            else ["关注/主页访问缺失"]
        ),
        "publishing_stability": [f"recent_publish_count_30d={count}", "目标约 10–14 篇/30d"],
        "content_verticality": (
            [f"top_category_share={max(category_values):.2f}", f"categories={len(category_values)}"]
            if category_values
            else ["category_distribution 空，默认 0.5"]
        ),
        "risk_and_violations": (
            [
                f"violation_count_90d={data.violation_count_90d}",
                f"deleted_note_count_90d={data.deleted_note_count_90d}",
            ]
            if data.violation_count_90d is not None and data.deleted_note_count_90d is not None
            else ["风险字段缺失"]
        ),
    }
    dimensions = {
        key: DimensionScore(
            score=round(value, 2),
            weight=WEIGHTS[key],
            evidence=evidence_map.get(key, []),
        )
        for key, value in raw.items()
    }
    weighted_score = sum(raw[key] * weight for key, weight in WEIGHTS.items())
    adjusted = weighted_score * (0.75 + 0.25 * completeness)
    strengths = [key for key, value in raw.items() if value >= 75]
    risks = [key for key, value in raw.items() if value < 45]
    actions = []
    if search < 60:
        actions.append("增加回答明确搜索问题的常青笔记，并覆盖长尾场景词。")
    if save_share < 60:
        actions.append("提高可收藏清单、比较标准和可复用步骤的比例。")
    if publishing_stability < 60:
        actions.append("建立稳定发布节奏，避免短期密集发布后长期停更。")
    if risk_score < 80:
        actions.append("优先处理违规、删除和账号功能限制风险。")
    return AccountWeightReport(
        overall_score=round(_bounded(adjusted), 2),
        confidence="HIGH" if completeness >= 0.8 else "MEDIUM",
        data_completeness=completeness,
        dimensions=dimensions,
        strengths=strengths,
        risks=risks,
        recommended_actions=actions,
        missing_data=missing,
    )
