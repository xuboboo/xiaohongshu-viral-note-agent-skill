"""账号健康度驱动选题策略：弱项补齐 + 强项放大（非官方算法）。"""

from __future__ import annotations

from typing import Any

# 维度 → 优先笔记类型、选题角度、话题后缀、理由
_DIM_STRATEGY: dict[str, dict[str, Any]] = {
    "save_share_value": {
        "note_styles": ["checklist", "comparison", "tutorial"],
        "angles": ["清单收藏", "对比决策", "可复用步骤"],
        "topic_suffixes": ["清单", "对照表", "步骤拆解", "怎么选"],
        "reason": "收藏/分享偏弱：优先清单、对比、步骤类，提高可收藏价值。",
        "priority": 10,
    },
    "search_mix": {
        "note_styles": ["decision", "tutorial", "avoid_pitfall"],
        "angles": ["搜索决策", "长尾场景", "问题解答"],
        "topic_suffixes": ["怎么选", "适合谁", "避坑", "值不值得"],
        "reason": "搜索流量占比偏低：优先问题型标题与长尾场景选题。",
        "priority": 10,
    },
    "interaction_efficiency": {
        "note_styles": ["seeding", "review", "store_visit"],
        "angles": ["场景共鸣", "互动提问", "真实边界"],
        "topic_suffixes": ["真实场景", "你会怎么选", "评论区聊聊"],
        "reason": "互动效率偏低：用强场景钩子 + 具体选择题结尾。",
        "priority": 8,
    },
    "performance_stability": {
        "note_styles": ["decision", "checklist", "review"],
        "angles": ["固定结构复用", "系列化", "机制沉淀"],
        "topic_suffixes": ["系列①", "标准版", "模板复用"],
        "reason": "表现波动大：固定 2–3 个结构重复打磨，少换赛道。",
        "priority": 7,
    },
    "publishing_cadence": {
        "note_styles": ["checklist", "decision"],
        "angles": ["轻量快更", "短清单", "单点结论"],
        "topic_suffixes": ["3 分钟看懂", "速记版", "本周一点"],
        "reason": "发布节奏不稳：用短清单/单结论降低制作成本，先稳住频率。",
        "priority": 6,
    },
    "vertical_focus": {
        "note_styles": ["review", "comparison", "decision"],
        "angles": ["垂直深挖", "细分人群", "系列专题"],
        "topic_suffixes": ["垂直专题", "人群版", "进阶"],
        "reason": "内容垂直度不足：围绕主赛道深挖细分，少跨类目。",
        "priority": 6,
    },
    "risk_control": {
        "note_styles": ["decision", "avoid_pitfall"],
        "angles": ["合规表述", "边界声明", "可核验证据"],
        "topic_suffixes": ["边界说明", "怎么判断", "避免夸大"],
        "reason": "风险分偏低：选题避免功效承诺与极限词，强调边界与证据。",
        "priority": 9,
    },
}

_STRENGTH_BOOST: dict[str, dict[str, Any]] = {
    "save_share_value": {
        "note_styles": ["checklist", "tutorial"],
        "angles": ["强项放大-收藏"],
        "reason": "收藏能力是优势：继续做高信息密度清单/教程。",
    },
    "search_mix": {
        "note_styles": ["decision", "avoid_pitfall"],
        "angles": ["强项放大-搜索"],
        "reason": "搜索承接较好：加长尾问句与常青决策文。",
    },
    "interaction_efficiency": {
        "note_styles": ["seeding", "store_visit"],
        "angles": ["强项放大-互动"],
        "reason": "互动效率较好：保持场景化开场与评论区问题。",
    },
}


def health_topic_strategy(health: dict[str, Any]) -> dict[str, Any]:
    """从内容健康度输出选题策略。"""
    dims = health.get("dimensions") or {}
    weaknesses = list(health.get("weaknesses") or [])
    strengths = list(health.get("strengths") or [])
    # 若 weaknesses 空，用最低分维度
    if not weaknesses and dims:
        ranked = sorted(dims.items(), key=lambda kv: float(kv[1]))
        weaknesses = [k for k, v in ranked[:2] if float(v) < 60]

    preferred_styles: list[str] = []
    preferred_angles: list[str] = []
    topic_suffixes: list[str] = []
    drivers: list[dict[str, Any]] = []

    for dim in sorted(
        weaknesses,
        key=lambda d: -int(_DIM_STRATEGY.get(d, {}).get("priority", 0)),
    ):
        cfg = _DIM_STRATEGY.get(dim)
        if not cfg:
            continue
        drivers.append(
            {
                "dimension": dim,
                "score": dims.get(dim),
                "mode": "fix",
                "reason": cfg["reason"],
                "note_styles": cfg["note_styles"],
            }
        )
        for s in cfg["note_styles"]:
            if s not in preferred_styles:
                preferred_styles.append(s)
        for a in cfg["angles"]:
            if a not in preferred_angles:
                preferred_angles.append(a)
        for suf in cfg["topic_suffixes"]:
            if suf not in topic_suffixes:
                topic_suffixes.append(suf)

    for dim in strengths[:2]:
        cfg = _STRENGTH_BOOST.get(dim)
        if not cfg:
            continue
        drivers.append(
            {
                "dimension": dim,
                "score": dims.get(dim),
                "mode": "amplify",
                "reason": cfg["reason"],
                "note_styles": cfg["note_styles"],
            }
        )
        for s in cfg["note_styles"]:
            if s not in preferred_styles:
                preferred_styles.append(s)
        for a in cfg["angles"]:
            if a not in preferred_angles:
                preferred_angles.append(a)

    if not preferred_styles:
        preferred_styles = ["decision", "checklist", "review"]
        preferred_angles = ["场景决策", "清单收藏"]
        topic_suffixes = ["怎么选", "避坑", "清单"]
        drivers.append(
            {
                "dimension": "default",
                "mode": "balance",
                "reason": "健康度数据不足或较均衡：用决策+清单稳住基本盘。",
                "note_styles": preferred_styles,
            }
        )

    primary_style = preferred_styles[0]
    return {
        "score_type": "HEALTH_DRIVEN_TOPIC_STRATEGY",
        "overall_score": health.get("overall_score"),
        "level": health.get("level"),
        "primary_note_style": primary_style,
        "preferred_note_styles": preferred_styles[:5],
        "preferred_angles": preferred_angles[:6],
        "topic_suffixes": topic_suffixes[:8],
        "drivers": drivers[:6],
        "disclaimer": "选题策略由授权数据估算的内容健康度推导，不是平台推荐算法。",
    }


def seed_topics_from_strategy(
    strategy: dict[str, Any],
    *,
    base_topic: str | None = None,
    pillars: list[str] | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """无热门研究时，用策略+账号支柱生成选题种子。"""
    roots: list[str] = []
    if base_topic and base_topic.strip():
        roots.append(base_topic.strip())
    for p in pillars or []:
        if p and str(p).strip() and str(p).strip() not in roots:
            roots.append(str(p).strip()[:40])
    if not roots:
        roots = ["本周选题"]

    suffixes = list(strategy.get("topic_suffixes") or ["怎么选", "清单", "避坑"])
    styles = list(strategy.get("preferred_note_styles") or ["decision"])
    angles = list(strategy.get("preferred_angles") or ["场景决策"])
    drivers = strategy.get("drivers") or []
    reason_default = (
        drivers[0]["reason"] if drivers and isinstance(drivers[0], dict) else "按账号健康度补齐弱项"
    )

    suggestions: list[dict[str, Any]] = []
    seen: set[str] = set()
    style_i = 0
    for root in roots:
        for suf in suffixes:
            topic = f"{root}{suf}" if not root.endswith(suf) else root
            key = topic.casefold()
            if key in seen:
                continue
            seen.add(key)
            style = styles[style_i % len(styles)]
            angle = angles[style_i % len(angles)]
            style_i += 1
            suggestions.append(
                {
                    "topic": topic[:80],
                    "angle": angle,
                    "reason": reason_default,
                    "gap_score": 0.55,
                    "source": "account_health",
                    "note_style": style,
                    "health_fit": 0.7,
                    "next_action": "generate_xhs_note",
                }
            )
            if len(suggestions) >= limit:
                return suggestions
    return suggestions


def score_suggestion_for_health(
    suggestion: dict[str, Any],
    strategy: dict[str, Any],
) -> float:
    """给热门选题打健康度契合分 0–1。"""
    styles = set(strategy.get("preferred_note_styles") or [])
    angles = [str(a).lower() for a in (strategy.get("preferred_angles") or [])]
    suffixes = [str(s) for s in (strategy.get("topic_suffixes") or [])]
    blob = " ".join(
        str(suggestion.get(k) or "") for k in ("topic", "angle", "reason", "note_style", "source")
    )
    blob_l = blob.lower()
    score = 0.25
    note_style = str(suggestion.get("note_style") or "").lower()
    if note_style in styles:
        score += 0.35
    # 角度/后缀命中
    if any(a and a in blob_l for a in angles):
        score += 0.15
    if any(suf and suf in blob for suf in suffixes):
        score += 0.15
    # 风险弱项时压低种草/功效向
    drivers = strategy.get("drivers") or []
    risk_fix = any(
        isinstance(d, dict) and d.get("dimension") == "risk_control" and d.get("mode") == "fix"
        for d in drivers
    )
    if risk_fix and any(x in blob_l for x in ("功效", "根治", "100%", "闭眼", "必入")):
        score -= 0.25
    gap = float(suggestion.get("gap_score") or 0.4)
    score += min(0.2, gap * 0.2)
    return max(0.0, min(1.0, round(score, 4)))


def rank_suggestions_by_health(
    suggestions: list[dict[str, Any]],
    strategy: dict[str, Any],
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """按健康度契合重排选题，并写入 health_fit / health_reason。"""
    primary = strategy.get("primary_note_style")
    ranked: list[dict[str, Any]] = []
    for item in suggestions:
        row = dict(item)
        # 若无 note_style，用策略主类型兜底
        if not row.get("note_style") and primary:
            row["note_style"] = primary
        fit = score_suggestion_for_health(row, strategy)
        row["health_fit"] = fit
        row["health_reason"] = _health_reason(row, strategy, fit)
        # 综合：健康契合 0.55 + 原 gap 0.45
        gap = float(row.get("gap_score") or 0.4)
        row["rank_score"] = round(0.55 * fit + 0.45 * min(1.0, gap), 4)
        ranked.append(row)
    ranked.sort(key=lambda x: float(x.get("rank_score") or 0), reverse=True)
    return ranked[:limit]


def _health_reason(suggestion: dict[str, Any], strategy: dict[str, Any], fit: float) -> str:
    drivers = strategy.get("drivers") or []
    if drivers and isinstance(drivers[0], dict):
        base = str(drivers[0].get("reason") or "")
    else:
        base = "结合账号健康度排序"
    style = suggestion.get("note_style") or ""
    return f"{base} 契合分={fit:.2f}；建议形态={style or strategy.get('primary_note_style')}。"


def merge_health_and_research_suggestions(
    *,
    health: dict[str, Any],
    research_suggestions: list[dict[str, Any]] | None = None,
    base_topic: str | None = None,
    pillars: list[str] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """健康策略 +（可选）热门选题 → 统一列表。"""
    strategy = health_topic_strategy(health)
    research = list(research_suggestions or [])
    if research:
        # 先给研究选题补 note_style 再排序
        from xhs_skill.orchestrator.hot_to_note import enrich_suggestions

        research = enrich_suggestions(research)
        ranked = rank_suggestions_by_health(research, strategy, limit=limit)
        source_mix = "research+health"
    else:
        seeds = seed_topics_from_strategy(
            strategy, base_topic=base_topic, pillars=pillars, limit=limit
        )
        ranked = rank_suggestions_by_health(seeds, strategy, limit=limit)
        source_mix = "health_only"

    # 统一 generate_payload
    from xhs_skill.operations.publish_timing import generate_request_from_suggestion

    for row in ranked:
        style = row.get("note_style") or strategy.get("primary_note_style")
        framework = {
            "avoid_pitfall": "pas",
            "checklist": "scqa",
            "comparison": "scqa",
            "tutorial": "quest",
            "store_visit": "bab",
            "review": "four_p",
            "seeding": "aida",
            "decision": "pas",
        }.get(str(style), "pas")
        row["narrative_framework"] = row.get("narrative_framework") or framework
        row["generate_payload"] = generate_request_from_suggestion(
            row,
            research_current_trends=bool(research),
            note_style=style,
            narrative_framework=row["narrative_framework"],
        )
        row["next_action"] = "generate_xhs_note"

    return {
        "strategy": strategy,
        "topic_suggestions": ranked,
        "source_mix": source_mix,
        "disclaimer": strategy.get("disclaimer"),
    }