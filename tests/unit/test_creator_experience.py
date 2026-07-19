"""选题建议 / 结构诊断 / 复盘下一篇契约。"""

from __future__ import annotations

from xhs_skill.generation.diagnose_structure import structure_checks
from xhs_skill.operations.retrospective import build_retrospective
from xhs_skill.operations.models import PublishedMetrics
from xhs_skill.research.topic_suggest import suggest_topics_from_report
from xhs_skill.schemas.research import (
    ContentMechanism,
    HotNotesReport,
    ScoreType,
    TrendClass,
    TrendTopic,
)


def test_suggest_topics_from_gaps_and_trends():
    report = HotNotesReport(
        query="降噪耳机",
        time_range="7d",
        score_type=ScoreType.PUBLIC_INDEX_HOT_SCORE,
        notes=[],
        trends=[
            TrendTopic(
                topic="通勤降噪",
                trend_class=TrendClass.RISING,
                score=70,
                content_gap_score=0.7,
                evidence_note_ids=["n1"],
            )
        ],
        mechanisms=[
            ContentMechanism(
                topic_angle="避坑",
                user_problem="不知道怎么选",
                content_promise="先看场景",
            )
        ],
        content_gaps=[
            {
                "gap": "避坑",
                "gap_score": 0.9,
                "recommendation": "补失败案例",
            }
        ],
        coverage_warning="PUBLIC_INDEX",
    )
    items = suggest_topics_from_report(report, limit=6)
    assert 1 <= len(items) <= 8
    assert all("topic" in i and i.get("next_action") == "generate_xhs_note" for i in items)
    assert any("避坑" in i["topic"] or i["source"] == "content_gap" for i in items)


def test_structure_checks_flags_missing_cta_and_topics():
    result = structure_checks(
        title="标题很长且具体",
        body="首段完全不提标题关键词。\n\n第二段也没有行动号召。",
        cta="",
        pinned_comment="",
        topics=[],
        hashtags=[],
    )
    assert result["passed"] is False
    assert any("CTA" in f or "话题" in f or "标题" in f for f in result["recommended_fixes"])


def test_retrospective_next_note_has_generate_action():
    metrics = PublishedMetrics(
        tenant_id="t",
        account_id="a",
        note_id="n1",
        views=1000,
        likes=10,
        saves=5,
        comments=1,
        search_views=50,
        content_features={"topic": "露营炉"},
    )
    retro = build_retrospective(metrics, [])
    assert retro.next_note_suggestions
    first = retro.next_note_suggestions[0]
    assert first.get("topic")
    assert first.get("next_action") == "generate_xhs_note"
    assert first.get("source")


def test_calendar_accepts_fallback_topics():
    from xhs_skill.operations.planning import build_content_calendar

    items = build_content_calendar(
        account_id="acc",
        topics=[],
        fallback_topics=["主题A", "主题B"],
        days=14,
        posts_per_week=2,
    )
    assert items
    assert any(i.topic in {"主题A", "主题B"} for i in items)