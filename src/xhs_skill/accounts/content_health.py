"""内容健康度：基于授权笔记表现估算，非官方分。"""

from __future__ import annotations

import math
import statistics
from typing import Any

from xhs_skill.schemas.account import AccountAnalytics


def _wilson_lower(successes: float, n: float, z: float = 1.645) -> float | None:
    """Wilson 得分区间下界（约 90%）。"""
    if n <= 0:
        return None
    p = max(0.0, min(1.0, successes / n))
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return max(0.0, (centre - margin) / denom)


def estimate_content_health(data: AccountAnalytics) -> dict[str, Any]:
    """内容健康度 0–100 + 维度、证据与建议。"""
    notes = list(data.note_performance or [])
    views = data.views_30d or 0
    likes = data.likes_30d or 0
    saves = data.saves_30d or 0
    comments = data.comments_30d or 0
    shares = data.shares_30d or 0
    publish_30 = data.recent_publish_count_30d or 0

    dim_evidence: dict[str, list[str]] = {}
    rate_ci: dict[str, Any] = {}

    # 互动效率
    if views > 0:
        eng_count = likes + 2 * saves + 1.5 * comments + 2 * shares
        eng = eng_count / views
        interaction = max(0.0, min(100.0, eng / 0.08 * 100))
        # 贝叶斯平滑率 + Wilson 下界（用 likes 作成功近似）
        bayes_rate = (likes + 8) / (views + 200)
        low = _wilson_lower(float(likes), float(views))
        rate_ci["interaction"] = {
            "point": round(eng, 5),
            "bayes_like_rate": round(bayes_rate, 5),
            "wilson_low_like_rate": round(low, 5) if low is not None else None,
            "n_views": views,
        }
        dim_evidence["interaction_efficiency"] = [
            f"views_30d={views}",
            f"weighted_eng_rate={eng:.4f}",
            f"wilson_low_like={low:.4f}" if low is not None else "wilson=n/a",
        ]
        if views < 500:
            dim_evidence["interaction_efficiency"].append("小样本：置信降低")
    else:
        interaction = 40.0
        dim_evidence["interaction_efficiency"] = ["views_30d 缺失，用中性先验 40"]

    # 收藏分享价值
    if views > 0:
        save_share_rate = (saves + 1.5 * shares) / views
        save_share = max(0.0, min(100.0, save_share_rate / 0.03 * 100))
        low_ss = _wilson_lower(float(saves + shares), float(views))
        rate_ci["save_share"] = {
            "point": round(save_share_rate, 5),
            "wilson_low": round(low_ss, 5) if low_ss is not None else None,
        }
        dim_evidence["save_share_value"] = [
            f"saves={saves}",
            f"shares={shares}",
            f"rate={save_share_rate:.4f}",
        ]
    else:
        save_share = 40.0
        dim_evidence["save_share_value"] = ["views 缺失"]

    # 发布节奏
    if publish_30 <= 0:
        cadence = 25.0
        dim_evidence["publishing_cadence"] = ["recent_publish_count_30d=0"]
    else:
        cadence = max(0.0, min(100.0, 100 - abs(publish_30 - 10) * 6))
        dim_evidence["publishing_cadence"] = [f"publish_30d={publish_30}", "目标约 8–12 篇/30d"]

    # 内容稳定性
    scores = []
    for note in notes:
        if note.get("normalized_score") is not None:
            scores.append(float(note["normalized_score"]))
        elif note.get("views"):
            scores.append(min(100.0, float(note["views"]) / 1000))
    if len(scores) >= 2:
        spread = statistics.pstdev(scores)
        stability = max(0.0, min(100.0, 90 - spread * 0.8))
        dim_evidence["performance_stability"] = [
            f"note_n={len(scores)}",
            f"pstdev={spread:.2f}",
        ]
    elif scores:
        stability = min(100.0, statistics.fmean(scores))
        dim_evidence["performance_stability"] = [f"单样本 score={scores[0]:.1f}"]
    else:
        stability = 45.0
        dim_evidence["performance_stability"] = ["note_performance 空"]

    # 搜索占比
    search_views = data.search_views_30d
    if search_views is not None and views > 0:
        search_mix = max(0.0, min(100.0, (search_views / views) / 0.25 * 100))
        dim_evidence["search_mix"] = [f"search_views={search_views}", f"share={search_views / views:.3f}"]
    else:
        search_mix = 50.0
        dim_evidence["search_mix"] = ["search_views 缺失，中性 50"]

    # 垂直度 + 漂移
    cats = list(data.category_distribution.values()) if data.category_distribution else []
    if cats:
        verticality = max(cats) * 100
        # 熵近似：分布越平漂移风险越高
        total = sum(cats) or 1.0
        probs = [c / total for c in cats if c > 0]
        entropy = -sum(p * math.log(p + 1e-12) for p in probs)
        max_ent = math.log(len(probs)) if len(probs) > 1 else 1.0
        drift_risk = entropy / max_ent if max_ent else 0.0
        dim_evidence["vertical_focus"] = [
            f"top_share={max(cats):.2f}",
            f"drift_risk={drift_risk:.2f}",
            f"categories={len(cats)}",
        ]
    else:
        verticality = 50.0
        drift_risk = 0.5
        dim_evidence["vertical_focus"] = ["category_distribution 空"]

    # 风险
    viol = data.violation_count_90d
    deleted = data.deleted_note_count_90d
    if viol is not None and deleted is not None:
        risk = max(0.0, min(100.0, 100 - viol * 25 - deleted * 3))
        dim_evidence["risk_control"] = [f"violations_90d={viol}", f"deleted_90d={deleted}"]
    else:
        risk = 55.0
        dim_evidence["risk_control"] = ["违规/删除字段缺失"]

    dims = {
        "interaction_efficiency": round(interaction, 1),
        "save_share_value": round(save_share, 1),
        "publishing_cadence": round(cadence, 1),
        "performance_stability": round(stability, 1),
        "search_mix": round(search_mix, 1),
        "vertical_focus": round(verticality, 1),
        "risk_control": round(risk, 1),
    }
    weights = {
        "interaction_efficiency": 0.22,
        "save_share_value": 0.18,
        "publishing_cadence": 0.12,
        "performance_stability": 0.15,
        "search_mix": 0.12,
        "vertical_focus": 0.11,
        "risk_control": 0.10,
    }
    overall = sum(dims[k] * weights[k] for k in weights)
    overall = round(max(0.0, min(100.0, overall)), 1)

    # 子分贡献（轻量 shap-like）
    contributions = {
        k: round((dims[k] - 50.0) * weights[k], 2) for k in weights
    }

    if overall >= 75:
        level = "健康"
    elif overall >= 55:
        level = "一般"
    elif overall >= 40:
        level = "偏弱"
    else:
        level = "需改善"

    strengths = [k for k, v in dims.items() if v >= 70]
    weaknesses = [k for k, v in dims.items() if v < 50]
    if drift_risk >= 0.75 and "vertical_focus" not in weaknesses:
        weaknesses.append("vertical_focus")

    actions: list[str] = []
    if dims["save_share_value"] < 55:
        actions.append("提高清单/对比/步骤类内容占比，增强收藏动机。")
    if dims["search_mix"] < 55:
        actions.append("标题与首段覆盖明确搜索问题与长尾场景词。")
    if dims["publishing_cadence"] < 55:
        actions.append("稳定周更节奏，避免暴更后停更。")
    if dims["performance_stability"] < 55:
        actions.append("复盘低分笔记机制，固定 2–3 个可复用结构。")
    if dims["risk_control"] < 70:
        actions.append("处理违规与高频删除，避免影响分发。")
    if drift_risk >= 0.75:
        actions.append("类目分布过散，收敛主赛道后再跨界。")
    if not actions:
        actions.append("保持现有优势机制，用小样本 A/B 优化标题与封面。")

    confidence = "HIGH"
    if views < 500 or len(notes) < 2:
        confidence = "LOW"
    elif views < 3000:
        confidence = "MEDIUM"

    return {
        "score_type": "ESTIMATED_CONTENT_HEALTH",
        "overall_score": overall,
        "level": level,
        "confidence": confidence,
        "dimensions": dims,
        "dimension_evidence": dim_evidence,
        "dimension_contributions": contributions,
        "rate_intervals": rate_ci,
        "vertical_drift_risk": round(drift_risk, 3) if cats else None,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "recommended_actions": actions[:6],
        "sample_notes": len(notes),
        "disclaimer": "内容健康度为授权数据估算，不是小红书官方账号或内容质量分。",
    }