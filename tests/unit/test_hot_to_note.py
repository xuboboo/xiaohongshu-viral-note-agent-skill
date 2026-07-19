"""热门→选题→一键生成。"""

from __future__ import annotations

import pytest

from xhs_skill.orchestrator.hot_to_note import (
    build_generate_request_from_hot,
    enrich_suggestions,
    infer_framework,
    infer_note_style,
    pick_suggestion,
    run_hot_to_note,
)
from xhs_skill.orchestrator.workflow import ContentWorkflow
from xhs_skill.schemas.research import (
    ContentMechanism,
    HotNotesReport,
    ScoreType,
    TrendClass,
    TrendTopic,
)


def test_infer_style_from_suggestion():
    assert infer_note_style({"topic": "耳机避坑", "angle": "失败"}) == "avoid_pitfall"
    assert infer_note_style({"topic": "清单核对", "source": "gap"}) == "checklist"
    assert infer_framework("review") == "four_p"


def test_enrich_and_pick():
    suggestions = enrich_suggestions(
        [
            {
                "topic": "降噪耳机｜避坑",
                "angle": "避坑",
                "reason": "补边界",
                "gap_score": 0.9,
                "source": "content_gap",
            },
            {
                "topic": "通勤降噪",
                "angle": "RISING",
                "reason": "上升",
                "gap_score": 0.5,
                "source": "trend",
            },
        ]
    )
    assert suggestions[0]["generate_payload"]["research_current_trends"] is False
    assert suggestions[0]["note_style"] == "avoid_pitfall"
    idx, selected = pick_suggestion(suggestions, index=1)
    assert idx == 1
    assert selected["topic"] == "通勤降噪"
    _, by_topic = pick_suggestion(suggestions, topic="降噪耳机｜避坑")
    assert "避坑" in by_topic["topic"]


def test_build_request_reuses_research_flag():
    sug = enrich_suggestions(
        [{"topic": "主题A", "angle": "决策", "reason": "r", "gap_score": 0.4, "source": "trend"}]
    )[0]
    req = build_generate_request_from_hot(sug, query="降噪耳机", format="graphic")
    assert req.research_current_trends is False
    assert req.suggested_topic == "主题A"
    assert req.topic == "降噪耳机"


@pytest.mark.asyncio
async def test_run_hot_to_note_dry_and_generate():
    class FakeResearch:
        async def search_hot_notes(self, query, **kwargs):
            return HotNotesReport(
                query=query.query,
                time_range="7d",
                score_type=ScoreType.PUBLIC_INDEX_HOT_SCORE,
                notes=[],
                trends=[
                    TrendTopic(
                        topic="通勤场景",
                        trend_class=TrendClass.RISING,
                        score=70,
                        content_gap_score=0.7,
                    )
                ],
                mechanisms=[
                    ContentMechanism(
                        topic_angle="避坑",
                        user_problem="不会选",
                        content_promise="给标准",
                    )
                ],
                content_gaps=[
                    {"gap": "避坑", "gap_score": 0.9, "recommendation": "补失败案例"}
                ],
                hot_insights={"summary": "ok"},
                coverage_warning="公开索引",
            )

    class FakeGeneration:
        async def generate(self, request, report, tenant_id="local"):
            from xhs_skill.schemas.content import DeliveryPackage

            return DeliveryPackage(
                task_id="t",
                trace_id="r",
                selected_title=request.suggested_topic or request.topic,
                body=f"正文关于{request.suggested_topic}\n\n场景。\n\n边界。",
                content_hash="h",
                topics=[request.topic],
                hashtags=[f"#{request.topic}"],
                quality_report={},
            )

    wf = ContentWorkflow()
    wf.research = FakeResearch()
    wf.generation = FakeGeneration()

    dry = await run_hot_to_note(wf, query="降噪耳机", dry_run=True, providers=["fixture"])
    assert dry["status"] == "suggestions_ready"
    assert dry["topic_suggestions"]
    assert dry["selected_suggestion"]["generate_payload"]

    full = await run_hot_to_note(
        wf,
        query="降噪耳机",
        dry_run=False,
        suggestion_index=0,
        providers=["fixture"],
    )
    assert full["status"] == "generated"
    assert full["package"]["selected_title"]
    assert full["package"]["creation_bundle"]
    assert full["generate_request"]["research_current_trends"] is False