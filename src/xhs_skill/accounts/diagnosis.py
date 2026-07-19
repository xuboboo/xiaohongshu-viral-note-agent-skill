"""账号联合诊断：权重 + 内容健康度 → 冲突解释 + generate_payload。"""

from __future__ import annotations

from typing import Any

from xhs_skill.operations.publish_timing import generate_request_from_suggestion

# 健康度弱项 → 默认生成参数
_ACTION_MAP: dict[str, dict[str, Any]] = {
    "save_share_value": {
        "note_style": "checklist",
        "narrative_framework": "scqa",
        "topic_suffix": "清单",
        "reason": "收藏/分享偏弱，优先清单与对比结构。",
    },
    "search_mix": {
        "note_style": "decision",
        "narrative_framework": "pas",
        "topic_suffix": "怎么选",
        "objective": "search_growth",
        "distribution_mode": "search",
        "reason": "搜索占比偏低，优先问题型决策文。",
    },
    "interaction_efficiency": {
        "note_style": "seeding",
        "narrative_framework": "aida",
        "topic_suffix": "你会怎么选",
        "reason": "互动效率偏低，加强场景钩子与评论提问。",
    },
    "performance_stability": {
        "note_style": "decision",
        "narrative_framework": "pas",
        "topic_suffix": "标准版",
        "reason": "表现波动大，固定结构复用。",
    },
    "publishing_cadence": {
        "note_style": "checklist",
        "narrative_framework": "scqa",
        "topic_suffix": "速记版",
        "reason": "节奏不稳，用短清单降低制作成本。",
    },
    "vertical_focus": {
        "note_style": "review",
        "narrative_framework": "four_p",
        "topic_suffix": "垂直专题",
        "reason": "垂直度不足，围绕主赛道深挖。",
    },
    "risk_control": {
        "note_style": "avoid_pitfall",
        "narrative_framework": "pas",
        "topic_suffix": "边界说明",
        "reason": "风险分偏低，强调边界与可核验证据。",
    },
}


def conflict_notes(weight: dict[str, Any], health: dict[str, Any]) -> list[str]:
    """两套分数不一致时的可读解释。"""
    notes: list[str] = []
    w_score = weight.get("overall_score")
    h_score = health.get("overall_score")
    if w_score is None and h_score is not None:
        notes.append("权重数据不足（INSUFFICIENT_DATA），内容健康度仍可作选题参考。")
    if weight.get("status") == "INSUFFICIENT_DATA":
        notes.append("账号权重缺关键字段，勿把内容健康度当作分发能力。")
    if w_score is not None and h_score is not None:
        delta = float(w_score) - float(h_score)
        if delta >= 15:
            notes.append(
                f"权重({w_score})明显高于内容健康度({h_score})：分发面尚可，内容生产/互动结构需补。"
            )
        elif delta <= -15:
            notes.append(
                f"内容健康度({h_score})明显高于权重({w_score})：单篇质量尚可，账号面/风险/完整度拖后腿。"
            )
    w_risks = set(weight.get("risks") or [])
    h_weak = set(health.get("weaknesses") or [])
    if "risk_and_violations" in w_risks or "risk_control" in h_weak:
        notes.append("风险相关维度偏弱：先处理违规/删除，再谈选题放量。")
    return notes[:6]


def build_generate_payloads_from_diagnosis(
    *,
    account_id: str,
    weight: dict[str, Any],
    health: dict[str, Any],
    base_topic: str | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """把诊断弱项映射为可一跳 generate 的 payload 列表。"""
    dims = health.get("dimensions") or {}
    weaknesses = list(health.get("weaknesses") or [])
    if not weaknesses and dims:
        ranked = sorted(dims.items(), key=lambda kv: float(kv[1]))
        weaknesses = [k for k, v in ranked[:3] if float(v) < 60]
    if not weaknesses:
        weaknesses = ["search_mix", "save_share_value"]

    root = (base_topic or "").strip() or "本周选题"
    payloads: list[dict[str, Any]] = []
    seen: set[str] = set()
    for dim in weaknesses:
        cfg = _ACTION_MAP.get(dim)
        if not cfg:
            continue
        suffix = str(cfg.get("topic_suffix") or "")
        topic = f"{root}{suffix}" if suffix and suffix not in root else root
        key = topic.casefold()
        if key in seen:
            continue
        seen.add(key)
        suggestion = {
            "topic": topic[:80],
            "angle": cfg.get("reason", dim)[:40],
            "reason": cfg.get("reason"),
            "note_style": cfg.get("note_style"),
            "source": "account_diagnosis",
        }
        payload = generate_request_from_suggestion(
            suggestion,
            research_current_trends=False,
            note_style=cfg.get("note_style"),
            narrative_framework=cfg.get("narrative_framework"),
            objective=cfg.get("objective") or "search_growth",
            distribution_mode=cfg.get("distribution_mode"),
            account_id=account_id,
        )
        payloads.append(
            {
                "dimension": dim,
                "topic": topic[:80],
                "reason": cfg.get("reason"),
                "note_style": cfg.get("note_style"),
                "narrative_framework": cfg.get("narrative_framework"),
                "next_action": "generate_xhs_note",
                "generate_payload": payload,
            }
        )
        if len(payloads) >= limit:
            break
    return payloads


def assemble_diagnosis(
    *,
    account_id: str,
    weight: dict[str, Any],
    health: dict[str, Any],
    base_topic: str | None = None,
    weight_anomalies: dict[str, Any] | None = None,
) -> dict[str, Any]:
    combined = list(
        dict.fromkeys(
            list(weight.get("recommended_actions") or [])
            + list(health.get("recommended_actions") or [])
        )
    )[:8]
    # 异常/冷启动动作并入
    for block_key in ("analytics_anomalies",):
        block = health.get(block_key) or {}
        for alert in block.get("alerts") or []:
            if isinstance(alert, dict) and alert.get("action") and alert["action"] not in combined:
                combined.append(str(alert["action"]))
    if weight_anomalies:
        for alert in weight_anomalies.get("alerts") or []:
            if isinstance(alert, dict) and alert.get("action") and alert["action"] not in combined:
                combined.append(str(alert["action"]))
    cold = health.get("coldstart") or {}
    if cold.get("is_coldstart"):
        for prior in cold.get("priors") or []:
            if isinstance(prior, dict) and prior.get("reason"):
                msg = f"冷启动：{prior['reason']}"
                if msg not in combined:
                    combined.append(msg)
    combined = combined[:10]

    generate_actions = build_generate_payloads_from_diagnosis(
        account_id=account_id,
        weight=weight,
        health=health,
        base_topic=base_topic,
    )
    # 冷启动时强制决策/清单风格
    if cold.get("is_coldstart") and generate_actions:
        for row in generate_actions:
            gp = row.get("generate_payload") or {}
            if not gp.get("note_style"):
                gp["note_style"] = "decision"
                row["generate_payload"] = gp
    primary = generate_actions[0]["generate_payload"] if generate_actions else None
    return {
        "account_id": account_id,
        "weight": weight,
        "content_health": health,
        "conflict_notes": conflict_notes(weight, health),
        "weight_anomalies": weight_anomalies or {},
        "coldstart": cold,
        "combined_actions": combined,
        "generate_actions": generate_actions,
        "generate_payload": primary,
        "disclaimer": (
            "联合诊断基于授权数据估算（ESTIMATED_ACCOUNT_WEIGHT / ESTIMATED_CONTENT_HEALTH），"
            "不是官方权重；generate_payload 仅作创作起点。"
        ),
    }