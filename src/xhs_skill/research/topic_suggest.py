"""从研究报吿生成可点选的选题建议（非官方热榜）。"""

from __future__ import annotations

from typing import Any

from xhs_skill.schemas.research import HotNotesReport, TrendClass


def suggest_topics_from_report(
    report: HotNotesReport,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """合并 content_gaps + 上升趋势 + 机制，输出 3–8 条可执行选题。

    每项：topic, angle, reason, gap_score, confidence, evidence_note_ids, next_action, source
    confidence 由 search_quality 调制：质量差时置信度下降，提醒用户多核实。
    """
    limit = max(3, min(int(limit), 8))
    suggestions: list[dict[str, Any]] = []
    seen: set[str] = set()

    # 质量分 → 置信度乘数
    quality = report.search_quality or {}
    q_score = float(quality.get("score") or 50)
    if q_score >= 70:
        confidence_mult = 1.0
        confidence_note = "样本质量良好，选题可信度高。"
    elif q_score >= 40:
        confidence_mult = 0.8
        confidence_note = "样本质量一般，建议结合账号定位再确认。"
    else:
        confidence_mult = 0.55
        confidence_note = "样本质量偏低，选题仅供参考，建议换词重搜或补充 web_results。"

    def _add(
        topic: str,
        *,
        angle: str,
        reason: str,
        gap_score: float,
        evidence_note_ids: list[str] | None = None,
        source: str,
    ) -> None:
        key = topic.strip().casefold()
        if not key or key in seen or len(topic) > 80:
            return
        seen.add(key)
        # gap_score × confidence_mult → 最终选题置信
        adjusted = round(float(gap_score) * confidence_mult, 4)
        suggestions.append(
            {
                "topic": topic.strip()[:80],
                "angle": (angle or "场景决策")[:40],
                "reason": reason[:200],
                "gap_score": adjusted,
                "confidence": adjusted,
                "confidence_note": confidence_note,
                "evidence_note_ids": list(evidence_note_ids or [])[:8],
                "next_action": "generate_xhs_note",
                "source": source,
            }
        )

    # 延迟：在函数末尾统一补 generate_payload

    for gap in report.content_gaps or []:
        if not isinstance(gap, dict):
            continue
        term = str(gap.get("gap") or "").strip()
        if not term:
            continue
        _add(
            f"{report.query}｜{term}" if report.query and term not in report.query else term,
            angle=str(gap.get("gap") or "内容缺口"),
            reason=str(gap.get("recommendation") or f"样本中“{term}”覆盖不足，适合补具体场景与边界。"),
            gap_score=float(gap.get("gap_score") or 0.5),
            source="content_gap",
        )

    for trend in report.trends or []:
        if trend.trend_class in {TrendClass.RISING, TrendClass.EMERGING, TrendClass.ANOMALOUS}:
            _add(
                trend.topic,
                angle=str(trend.trend_class),
                reason=(
                    f"趋势类 {trend.trend_class}，score={trend.score:.1f}，"
                    f"gap≈{trend.content_gap_score:.2f}（公开索引样本，非站内热榜）。"
                ),
                gap_score=max(trend.content_gap_score, 0.4),
                evidence_note_ids=list(trend.evidence_note_ids or []),
                source="trend",
            )

    for mechanism in (report.mechanisms or [])[:4]:
        angle = (mechanism.topic_angle or mechanism.title_mechanism or "机制").strip()
        problem = (mechanism.user_problem or "").strip()
        topic = f"{report.query}·{angle}" if report.query else angle
        if problem:
            topic = f"{report.query or angle}：{problem[:20]}"
        _add(
            topic,
            angle=angle,
            reason=mechanism.content_promise or f"机制「{angle}」可复用结构，勿复用原文表达。",
            gap_score=0.45,
            source="mechanism",
        )

    if not suggestions and report.query:
        _add(
            report.query,
            angle="决策支持",
            reason="样本不足以拆缺口，先以查询词做场景化决策笔记。",
            gap_score=0.3,
            source="query_fallback",
        )

    suggestions.sort(key=lambda item: item["confidence"], reverse=True)
    trimmed = suggestions[:limit]
    # 一跳生成载荷（与热门/健康选题同形；不 import orchestrator，避免循环依赖）
    from xhs_skill.operations.publish_timing import generate_request_from_suggestion

    for row in trimmed:
        blob = " ".join(str(row.get(k) or "") for k in ("topic", "angle", "reason", "source"))
        style = "decision"
        if any(x in blob for x in ("避坑", "翻车", "踩雷")):
            style = "avoid_pitfall"
        elif any(x in blob for x in ("清单", "checklist")):
            style = "checklist"
        elif any(x in blob for x in ("对比", "VS", "还是")):
            style = "comparison"
        elif any(x in blob for x in ("教程", "步骤")):
            style = "tutorial"
        framework = {
            "avoid_pitfall": "pas",
            "checklist": "scqa",
            "comparison": "scqa",
            "tutorial": "quest",
            "decision": "pas",
        }.get(style, "pas")
        row["note_style"] = row.get("note_style") or style
        row["narrative_framework"] = row.get("narrative_framework") or framework
        # 搜索向提示：来自样本意图（若 report 有 hot_insights）
        insights = report.hot_insights or {}
        playbook = insights.get("search_playbook") if isinstance(insights, dict) else None
        if isinstance(playbook, dict):
            row["search_intent"] = (playbook.get("query_intent") or {}).get("primary")
            km = playbook.get("keyword_matrix") or {}
            layers = km.get("hashtag_layers") if isinstance(km, dict) else None
            if isinstance(layers, dict):
                row["hashtag_hint"] = layers
            seo = playbook.get("seo_checklist") or (km.get("title_seo_hints") if isinstance(km, dict) else None)
            if seo:
                row["seo_hints"] = list(seo)[:5]
        row["generate_payload"] = generate_request_from_suggestion(
            row,
            research_current_trends=False,
            note_style=row["note_style"],
            narrative_framework=row["narrative_framework"],
        )
        # 把 SEO 约束塞进 constraints，生成侧可感知
        gp = row["generate_payload"]
        if isinstance(gp, dict):
            constraints = list(gp.get("constraints") or [])
            if row.get("seo_hints"):
                constraints.append("seo:" + ";".join(str(h) for h in row["seo_hints"][:3]))
            if row.get("hashtag_hint"):
                constraints.append("hashtags:3-5 core+longtail")
            # 质量边界：低质量样本时追加 evidence_boundary
            from xhs_skill.research.quality import generation_guards_from_quality

            guards = generation_guards_from_quality(report.search_quality)
            for gc in guards.get("constraints") or []:
                if gc not in constraints:
                    constraints.append(gc)
            gp["constraints"] = constraints
        row["next_action"] = "generate_xhs_note"
    return trimmed