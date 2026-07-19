"""账号权重/健康序列异常检测（残差阈值，非官方告警）。"""

from __future__ import annotations

import statistics
from typing import Any

from xhs_skill.schemas.account import AccountAnalytics, AccountWeightSnapshot


def detect_weight_anomalies(
    history: list[AccountWeightSnapshot],
    *,
    min_points: int = 3,
    z_threshold: float = 1.8,
) -> dict[str, Any]:
    """基于权重历史做简单残差异常。"""
    scores = [float(h.score) for h in history if h.score is not None]
    if len(scores) < min_points:
        return {
            "status": "insufficient_history",
            "alerts": [],
            "sample_n": len(scores),
            "disclaimer": "历史点不足，跳过异常检测。",
        }

    mean = statistics.fmean(scores[:-1]) if len(scores) > 1 else scores[0]
    stdev = statistics.pstdev(scores[:-1]) if len(scores) > 2 else 0.0
    latest = scores[-1]
    residual = latest - mean
    z = residual / stdev if stdev > 1e-6 else 0.0

    alerts: list[dict[str, Any]] = []
    if stdev > 0 and abs(z) >= z_threshold:
        direction = "drop" if residual < 0 else "spike"
        alerts.append(
            {
                "type": f"weight_{direction}",
                "latest": latest,
                "baseline_mean": round(mean, 2),
                "residual": round(residual, 2),
                "z": round(z, 3),
                "severity": ["metric_noise", "content_mix_shift", "risk_event"],
                "action": (
                    "权重骤降：优先查违规/删除与近期内容结构变化。"
                    if direction == "drop"
                    else "权重骤升：核对是否单篇异常，避免过拟合一篇。"
                ),
            }
        )
    # 连续下滑
    if len(scores) >= 3 and scores[-1] < scores[-2] < scores[-3]:
        alerts.append(
            {
                "type": "weight_downtrend",
                "latest": latest,
                "window": scores[-3:],
                "action": "连续 3 次下滑：稳住发布节奏并复盘低分机制。",
            }
        )

    return {
        "status": "ok",
        "alerts": alerts,
        "sample_n": len(scores),
        "latest": latest,
        "baseline_mean": round(mean, 2),
        "stdev": round(stdev, 2),
        "disclaimer": "异常检测基于本系统历史估算分，不是平台官方告警。",
    }


def detect_analytics_anomalies(data: AccountAnalytics) -> dict[str, Any]:
    """单快照启发式：互动/发布极端值。"""
    alerts: list[dict[str, Any]] = []
    views = data.views_30d or 0
    likes = data.likes_30d or 0
    publish = data.recent_publish_count_30d or 0
    viol = data.violation_count_90d
    deleted = data.deleted_note_count_90d

    if views > 0 and likes / views < 0.005 and views >= 3000:
        alerts.append(
            {
                "type": "low_like_rate",
                "detail": f"likes/views={likes / views:.4f}",
                "action": "互动率偏低：加强开头钩子与评论区问题。",
            }
        )
    if publish >= 25:
        alerts.append(
            {
                "type": "over_publishing",
                "detail": f"publish_30d={publish}",
                "action": "发布过密：降频并保证单篇完成度。",
            }
        )
    if publish == 0 and views == 0:
        alerts.append(
            {
                "type": "inactive",
                "detail": "近 30 天无发布/无曝光数据",
                "action": "先同步数据或恢复稳定周更。",
            }
        )
    if viol is not None and viol >= 1:
        alerts.append(
            {
                "type": "violation",
                "detail": f"violations_90d={viol}",
                "action": "存在违规记录：先处理风险再放量。",
            }
        )
    if deleted is not None and deleted >= 5:
        alerts.append(
            {
                "type": "high_delete",
                "detail": f"deleted_90d={deleted}",
                "action": "删除偏多：减少试错式发文，先过合规门。",
            }
        )

    return {
        "status": "ok" if alerts else "clean",
        "alerts": alerts,
        "disclaimer": "基于授权快照启发式，非官方风控。",
    }


def coldstart_prior(data: AccountAnalytics) -> dict[str, Any]:
    """新号冷启动先验：样本不足时给类目与节奏建议，不编造行业均值冒充分数。"""
    notes = data.published_note_count or 0
    followers = data.followers or 0
    completeness_proxy = sum(
        1
        for f in (
            data.views_30d,
            data.likes_30d,
            data.saves_30d,
            data.search_views_30d,
            data.recent_publish_count_30d,
        )
        if f is not None
    )
    is_cold = notes < 15 or followers < 500 or completeness_proxy < 3
    if not is_cold:
        return {
            "is_coldstart": False,
            "priors": [],
            "disclaimer": "账号样本已够，无需冷启动先验。",
        }

    cats = data.category_distribution or {}
    top_cat = max(cats, key=cats.get) if cats else None
    priors = [
        {
            "key": "cadence",
            "value": "2-3_per_week",
            "reason": "新号优先稳定周更，避免暴更后停更。",
        },
        {
            "key": "format_mix",
            "value": "graphic_heavy",
            "reason": "图文制作成本低，便于测机制。",
        },
        {
            "key": "note_styles",
            "value": ["decision", "checklist", "avoid_pitfall"],
            "reason": "搜索决策 + 清单收藏更容易积累可复用结构。",
        },
    ]
    if top_cat:
        priors.append(
            {
                "key": "vertical",
                "value": top_cat,
                "reason": f"已有类目信号「{top_cat}」，先垂直深挖再跨界。",
            }
        )
    else:
        priors.append(
            {
                "key": "vertical",
                "value": "pick_one_pillar",
                "reason": "类目分布空：先定 1 个内容支柱。",
            }
        )

    return {
        "is_coldstart": True,
        "signals": {
            "published_note_count": notes,
            "followers": followers,
            "filled_metrics": completeness_proxy,
        },
        "priors": priors,
        "disclaimer": "冷启动先验为创作建议，不是平台加权承诺。",
    }