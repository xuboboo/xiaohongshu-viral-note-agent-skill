from __future__ import annotations

from xhs_skill.operations.attribution import attribute_performance
from xhs_skill.operations.models import PublishedMetrics, Retrospective
from xhs_skill.operations.publish_timing import (
    calendar_topics_from_retrospective,
    generate_request_from_suggestion,
)


def build_retrospective(target: PublishedMetrics, history: list[PublishedMetrics]) -> Retrospective:
    attribution = attribute_performance(target, history)
    strengths = [
        item.feature
        for item in attribution.contributions
        if item.direction == "POSITIVE" and item.confidence >= 0.25
    ][:5]
    weaknesses = [
        item.feature
        for item in attribution.contributions
        if item.direction == "NEGATIVE" and item.confidence >= 0.25
    ][:5]
    actions: list[str] = []
    if target.search_views is not None and target.views and target.search_views / target.views < 0.15:
        actions.append("下一篇补充标题核心关键词、首段问题句和长尾场景词。")
    if target.saves is not None and target.views and target.saves / target.views < 0.02:
        actions.append("增加清单、对比标准、步骤和可复用模板，提高收藏价值。")
    if target.comments is not None and target.views and target.comments / target.views < 0.005:
        actions.append("结尾改为具体选择题或场景问题，避免空泛求互动。")
    if not actions:
        actions.append("保留有效机制，并通过小样本 A/B/n 实验验证标题或封面变化。")
    topic = str(target.content_features.get("topic", "同主题"))
    suggestions = [
        {
            "topic": f"{topic}避坑版",
            "angle": "失败边界",
            "reason": "补足失败案例和适用边界，提升决策价值。",
            "source": "metric_rule",
            "experiment": "对比清单型标题与问题型标题",
            "next_action": "generate_xhs_note",
        },
        {
            "topic": f"{topic}场景对比",
            "angle": "人群分层",
            "reason": "覆盖不同人群与预算，降低主题重复。",
            "source": "metric_rule",
            "experiment": "对比图文与短视频表达",
            "next_action": "generate_xhs_note",
        },
    ]
    if actions and "关键词" in actions[0]:
        suggestions.insert(
            0,
            {
                "topic": f"{topic}搜索词版",
                "angle": "搜索意图",
                "reason": "搜索占比偏低：用长尾场景词做标题与首段。",
                "source": "metric_rule",
                "experiment": "搜索向标题 vs 情绪向标题",
                "next_action": "generate_xhs_note",
            },
        )
    # 可直接喂 generate / calendar 的载荷
    for item in suggestions:
        item["generate_payload"] = generate_request_from_suggestion(item)
    retro = Retrospective(
        tenant_id=target.tenant_id,
        account_id=target.account_id,
        note_id=target.note_id,
        summary=(
            f"目标指标为 {attribution.metric_value:.4f}，历史中位基线为 "
            f"{attribution.baseline_value:.4f}，差值 {attribution.lift:.4f}。"
        ),
        strengths=strengths,
        weaknesses=weaknesses,
        next_actions=actions,
        next_note_suggestions=suggestions,
    )
    # 附加字段经 model_extra / 由调用方 dump 时并入 quality——Retrospective 若无 extra，写入 suggestions 即可
    return retro


def enrich_retrospective_dict(data: dict) -> dict:
    """为 API/MCP 输出附加 calendar_topics 与 generate 一跳字段。"""
    suggestions = data.get("next_note_suggestions") or []
    for item in suggestions:
        if isinstance(item, dict) and "generate_payload" not in item:
            item["generate_payload"] = generate_request_from_suggestion(item)
    data["next_note_suggestions"] = suggestions
    data["calendar_topics"] = calendar_topics_from_retrospective(data)
    data["calendar_payload"] = {
        "account_id": data.get("account_id"),
        "fallback_topics": data["calendar_topics"],
        "topics": data["calendar_topics"],
    }
    return data
