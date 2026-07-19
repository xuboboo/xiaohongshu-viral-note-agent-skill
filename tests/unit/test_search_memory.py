"""搜索质量记忆与自适应策略测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.research.query_expansion import expand_query
from xhs_skill.research.search_memory import (
    SearchQualityMemory,
    plan_search_strategy,
    quality_delta,
)
from xhs_skill.research.service import ResearchService
from xhs_skill.research.topic_suggest import suggest_topics_from_report
from xhs_skill.schemas.research import (
    HotNotesReport,
    ScoreType,
    SearchQuery,
    TrendClass,
    TrendTopic,
)
from xhs_skill.search.adaptive import ClientWebSearchRequired, trust_score, normalize_web_results
from xhs_skill.search.registry import SearchRegistry
from xhs_skill.ux.envelope import enrich_needs_web_search


def test_plan_strategy_default_without_baseline():
    s = plan_search_strategy(None)
    assert s["has_baseline"] is False
    assert s["max_variants"] == 6
    assert s["live_retries"] == 2


def test_plan_strategy_poor_deepens_expansion():
    prev = {
        "score": 25,
        "label": "poor",
        "recommendations": ["结果偏旧"],
        "metrics": {"freshness_72h": 0.1, "source_diversity": 0.2},
    }
    s = plan_search_strategy(prev)
    assert s["has_baseline"] is True
    assert s["max_variants"] >= 8
    assert s["variant_cap"] >= 6
    assert s["live_retries"] >= 3
    assert s["prefer_crowd_angles"] is True
    assert s["force_site_queries"] is True
    assert s["ttl_multiplier_boost"] <= 1.0


def test_plan_strategy_good_converges():
    prev = {"score": 85, "label": "good", "metrics": {"freshness_72h": 0.8}}
    s = plan_search_strategy(prev)
    assert s["max_variants"] <= 6
    assert s["live_retries"] <= 2
    assert s["ttl_multiplier_boost"] >= 1.0


def test_quality_delta_improved():
    d = quality_delta({"score": 70, "label": "good"}, {"score": 40, "label": "fair"})
    assert d["has_baseline"] is True
    assert d["score_delta"] == 30.0
    assert d["improved"] is True


def test_quality_memory_roundtrip(tmp_path: Path):
    mem = SearchQualityMemory(tmp_path / "sq")
    mem.save("通勤防晒", {"score": 55, "label": "fair", "recommendations": ["x"]}, note_count=3)
    loaded = mem.load("通勤防晒")
    assert loaded is not None
    assert loaded["score"] == 55
    assert loaded["label"] == "fair"
    assert mem.load("不存在的词") is None


def test_expand_query_respects_strategy_flags():
    shallow = expand_query("防晒霜", max_variants=6, prefer_crowd_angles=False)
    deep = expand_query(
        "防晒霜",
        max_variants=10,
        prefer_crowd_angles=True,
        force_site_queries=True,
    )
    assert len(deep) >= len(shallow)
    assert any("site:" in v for v in deep)


def test_topic_suggest_confidence_modulated_by_quality():
    base = dict(
        query="降噪耳机",
        time_range="7d",
        score_type=ScoreType.PUBLIC_INDEX_HOT_SCORE,
        notes=[],
        trends=[
            TrendTopic(
                topic="通勤降噪",
                trend_class=TrendClass.RISING,
                score=70,
                content_gap_score=0.9,
                evidence_note_ids=["n1"],
            )
        ],
        content_gaps=[{"gap": "避坑", "gap_score": 0.9, "recommendation": "补失败"}],
        coverage_warning="PUBLIC_INDEX",
    )
    good = suggest_topics_from_report(
        HotNotesReport(**base, search_quality={"score": 90, "label": "good"})
    )
    poor = suggest_topics_from_report(
        HotNotesReport(**base, search_quality={"score": 20, "label": "poor"})
    )
    assert good and poor
    assert good[0]["confidence"] > poor[0]["confidence"]
    assert "偏低" in poor[0]["confidence_note"] or "参考" in poor[0]["confidence_note"]


def test_topic_suggest_injects_quality_guards_into_generate_payload():
    base = dict(
        query="降噪耳机",
        time_range="7d",
        score_type=ScoreType.PUBLIC_INDEX_HOT_SCORE,
        notes=[],
        trends=[
            TrendTopic(
                topic="通勤降噪",
                trend_class=TrendClass.RISING,
                score=70,
                content_gap_score=0.9,
                evidence_note_ids=["n1"],
            )
        ],
        content_gaps=[{"gap": "避坑", "gap_score": 0.9, "recommendation": "补失败"}],
        coverage_warning="PUBLIC_INDEX",
    )
    poor = suggest_topics_from_report(
        HotNotesReport(**base, search_quality={"score": 20, "label": "poor"})
    )
    gp = poor[0].get("generate_payload") or {}
    constraints = gp.get("constraints") or []
    assert any("evidence_boundary" in c for c in constraints)
    assert any("disclaimer" in c for c in constraints)


def test_trust_score_prefers_xhs_explore():
    rows = normalize_web_results(
        [
            {"url": "https://www.xiaohongshu.com/explore/abc", "title": "通勤防晒清单详解", "snippet": "很长的摘要" * 3},
            {"url": "https://random-blog.example/page", "title": "随便一篇"},
        ]
    )
    assert trust_score(rows[0]) > trust_score(rows[1])


def test_needs_web_search_includes_previous_quality(tmp_path: Path, monkeypatch):
    mem = SearchQualityMemory(tmp_path / "sq")
    mem.save(
        "通勤防晒",
        {
            "score": 22,
            "label": "poor",
            "recommendations": ["结果偏旧，可缩短 time_range"],
            "metrics": {"freshness_72h": 0.1},
        },
        note_count=2,
    )

    class _Mem(SearchQualityMemory):
        def __init__(self, root: str | Path = "./data/search_quality") -> None:
            super().__init__(tmp_path / "sq")

    monkeypatch.setattr(
        "xhs_skill.research.search_memory.SearchQualityMemory",
        _Mem,
    )
    payload = ClientWebSearchRequired(
        "通勤防晒",
        suggested_queries=["通勤防晒 小红书"],
    ).to_payload()
    out = enrich_needs_web_search(payload)
    assert out["status"] == "needs_web_search"
    assert out["suggested_queries"]
    assert out.get("previous_search_quality", {}).get("label") == "poor"
    assert out.get("adaptive_strategy", {}).get("prefer_crowd_angles") is True
    assert out["minimum_results_hint"] >= 12
    assert len(out["suggested_queries"]) >= 2


@pytest.mark.asyncio
async def test_research_persists_quality_and_adapts(tmp_path, monkeypatch):
    get_settings.cache_clear()
    settings = Settings(
        app_env="test",
        app_secret_key="Aa1!" + "x" * 36,
        search_auto_fallback="delegate",
        model_providers_file=tmp_path / "missing.yaml",
        search_cache_ttl_seconds=60,
    )
    monkeypatch.setattr("xhs_skill.research.service.get_settings", lambda: settings)
    mem = SearchQualityMemory(tmp_path / "sq")
    service = ResearchService(SearchRegistry(settings), quality_memory=mem)

    report1 = await service.search_hot_notes(
        SearchQuery(query="通勤防晒", limit=5),
        web_results=[
            {
                "url": "https://www.xiaohongshu.com/explore/h1",
                "title": "通勤防晒避坑清单",
                "snippet": "点赞 800 收藏 1200 适合上班族",
            },
            {
                "url": "https://www.xiaohongshu.com/explore/h2",
                "title": "上班族防晒霜怎么选",
                "snippet": "真实使用一周 边界说明",
            },
        ],
    )
    assert report1.search_quality.get("score") is not None
    assert report1.search_quality.get("strategy") is not None
    assert report1.search_quality.get("delta", {}).get("has_baseline") is False
    loaded = mem.load("通勤防晒")
    assert loaded is not None
    assert loaded["score"] == report1.search_quality["score"]

    # 第二次应读到 baseline
    report2 = await service.search_hot_notes(
        SearchQuery(query="通勤防晒", limit=5),
        web_results=[
            {
                "url": "https://www.xiaohongshu.com/explore/h3",
                "title": "通勤防晒对比测评",
                "snippet": "场景与预算 收藏向",
            },
        ],
    )
    assert report2.search_quality.get("strategy", {}).get("has_baseline") is True
    assert report2.search_quality.get("delta", {}).get("has_baseline") is True
    assert report2.topic_suggestions
    assert "confidence" in report2.topic_suggestions[0]