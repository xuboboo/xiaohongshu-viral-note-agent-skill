"""账号健康度驱动选题。"""

from __future__ import annotations

from xhs_skill.accounts.content_health import estimate_content_health
from xhs_skill.accounts.health_topics import (
    health_topic_strategy,
    merge_health_and_research_suggestions,
    rank_suggestions_by_health,
    seed_topics_from_strategy,
)
from xhs_skill.accounts.service import AccountService
from xhs_skill.schemas.account import AccountAnalytics


def _weak_save_analytics() -> AccountAnalytics:
    return AccountAnalytics(
        account_id="acc-health",
        followers=2000,
        published_note_count=40,
        recent_publish_count_30d=4,
        views_30d=50000,
        likes_30d=800,
        saves_30d=50,  # 收藏弱
        comments_30d=40,
        shares_30d=20,
        search_views_30d=2000,  # 搜索弱相对 views
        recommendation_views_30d=48000,
        profile_visits_30d=500,
        follows_gained_30d=20,
        commercial_note_ratio=0.1,
        deleted_note_count_90d=0,
        violation_count_90d=0,
        category_distribution={"数码": 0.4, "生活": 0.3, "美妆": 0.3},
        note_performance=[
            {"normalized_score": 40, "views": 500},
            {"normalized_score": 90, "views": 5000},
        ],
    )


def test_health_strategy_prefers_checklist_when_save_weak():
    health = estimate_content_health(_weak_save_analytics())
    strategy = health_topic_strategy(health)
    assert strategy["preferred_note_styles"]
    # 收藏弱应出现清单/对比/教程
    styles = set(strategy["preferred_note_styles"])
    assert styles & {"checklist", "comparison", "tutorial"}
    assert strategy["drivers"]


def test_seed_and_rank_health_only():
    health = estimate_content_health(_weak_save_analytics())
    strategy = health_topic_strategy(health)
    seeds = seed_topics_from_strategy(strategy, base_topic="降噪耳机", limit=6)
    assert seeds
    assert all(s.get("source") == "account_health" for s in seeds)
    ranked = rank_suggestions_by_health(seeds, strategy, limit=5)
    assert ranked[0].get("health_fit") is not None
    assert ranked[0].get("generate_payload") is None  # rank only; merge adds payload


def test_merge_research_plus_health_reorders():
    health = estimate_content_health(_weak_save_analytics())
    research = [
        {
            "topic": "耳机种草安利",
            "angle": "种草",
            "reason": "热",
            "gap_score": 0.9,
            "source": "trend",
            "note_style": "seeding",
        },
        {
            "topic": "耳机避坑清单",
            "angle": "清单",
            "reason": "收藏",
            "gap_score": 0.5,
            "source": "content_gap",
            "note_style": "checklist",
        },
    ]
    merged = merge_health_and_research_suggestions(
        health=health,
        research_suggestions=research,
        base_topic="耳机",
        limit=5,
    )
    assert merged["source_mix"] == "research+health"
    topics = [t["topic"] for t in merged["topic_suggestions"]]
    # 清单应因健康契合排到前面（相对纯种草）
    assert any("清单" in t or t.get("note_style") == "checklist" for t in merged["topic_suggestions"])
    assert merged["topic_suggestions"][0].get("generate_payload")
    assert "耳机" in "".join(topics) or merged["topic_suggestions"]


def test_account_service_suggest_topics_from_health():
    svc = AccountService()
    data = _weak_save_analytics()
    out = svc.suggest_topics_from_health(
        "acc-health",
        analytics=data,
        base_topic="露营",
        limit=5,
    )
    assert out["topic_suggestions"]
    assert out["strategy"]["primary_note_style"]
    assert out["content_health"]["overall_score"] is not None


def test_hot_to_note_with_health_reorders():
    import asyncio

    from xhs_skill.orchestrator.hot_to_note import run_hot_to_note
    from xhs_skill.orchestrator.workflow import ContentWorkflow
    from xhs_skill.schemas.research import (
        ContentMechanism,
        HotNotesReport,
        ScoreType,
        TrendClass,
        TrendTopic,
    )

    class FakeResearch:
        async def search_hot_notes(self, query, **kwargs):
            return HotNotesReport(
                query=query.query,
                time_range="7d",
                score_type=ScoreType.PUBLIC_INDEX_HOT_SCORE,
                notes=[],
                trends=[
                    TrendTopic(
                        topic="种草热",
                        trend_class=TrendClass.RISING,
                        score=90,
                        content_gap_score=0.9,
                    )
                ],
                mechanisms=[ContentMechanism(topic_angle="种草", user_problem="不会买")],
                content_gaps=[
                    {"gap": "清单", "gap_score": 0.4, "recommendation": "补清单"},
                ],
                coverage_warning="公开索引",
            )

    class FakeGen:
        async def generate(self, request, report, tenant_id="local"):
            from xhs_skill.schemas.content import DeliveryPackage

            return DeliveryPackage(
                task_id="t",
                trace_id="r",
                selected_title=request.suggested_topic or request.topic,
                body="正文",
                content_hash="h",
                quality_report={},
            )

    class FakeAccounts(AccountService):
        def suggest_topics_from_health(self, account_id, **kwargs):
            research = kwargs.get("research_suggestions") or []
            return {
                "strategy": {
                    "primary_note_style": "checklist",
                    "preferred_note_styles": ["checklist"],
                },
                "topic_suggestions": [
                    {
                        "topic": "健康优先清单",
                        "note_style": "checklist",
                        "narrative_framework": "scqa",
                        "health_fit": 0.95,
                        "generate_payload": {
                            "topic": "健康优先清单",
                            "note_style": "checklist",
                            "research_current_trends": False,
                        },
                    },
                    *(research[:1]),
                ],
                "source_mix": "research+health",
                "content_health": {"level": "一般", "overall_score": 50},
            }

    wf = ContentWorkflow()
    wf.research = FakeResearch()
    wf.generation = FakeGen()
    out = asyncio.run(
        run_hot_to_note(
            wf,
            query="耳机",
            dry_run=True,
            account_id="acc-health",
            use_account_health=True,
            accounts_service=FakeAccounts(),
            providers=["fixture"],
        )
    )
    assert out["use_account_health"] is True
    assert out["topic_suggestions"][0]["topic"] == "健康优先清单"
    assert out["health_strategy"]