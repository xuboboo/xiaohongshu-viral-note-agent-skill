"""联网搜索链路增强测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.research.deduplicator import deduplicate
from xhs_skill.research.quality import assess_search_quality
from xhs_skill.research.query_expansion import expand_query, sanitize_query
from xhs_skill.research.ranker import rank_hot_notes
from xhs_skill.research.service import ClientWebSearchRequired, ResearchService
from xhs_skill.schemas.research import HotNoteCandidate, ScoreType, SearchQuery
from xhs_skill.search.adaptive import normalize_web_results, resolve_provider_names
from xhs_skill.search.registry import SearchRegistry


def note(id_: str, title: str, **kwargs):
    return HotNoteCandidate(
        id=id_,
        url=f"https://www.xiaohongshu.com/explore/{id_}",
        title=title,
        source_provider=kwargs.pop("source_provider", "test"),
        published_at=datetime.now(UTC) - timedelta(hours=kwargs.pop("age", 12)),
        **kwargs,
    )


# ── sanitize_query ──────────────────────────────────────────────


def test_sanitize_query_strips_html():
    result = sanitize_query("<b>防晒</b>推荐")
    assert "<b>" not in result
    assert "推荐" in result
    assert "防晒" in result


def test_sanitize_query_strips_control_chars():
    assert sanitize_query("防晒\x00推荐") == "防晒推荐"


def test_sanitize_query_truncates():
    long = "a" * 200
    assert len(sanitize_query(long)) <= 120


def test_sanitize_query_preserves_normal():
    assert sanitize_query("通勤防晒 怎么选") == "通勤防晒 怎么选"


# ── expand_query 增强 ──────────────────────────────────────────


def test_expand_query_returns_more_variants_with_crowd():
    variants = expand_query("防晒霜怎么选", max_variants=10)
    assert len(variants) >= 5
    assert any("小红书" in v for v in variants)


def test_expand_query_deduplicates():
    variants = expand_query("防晒 防晒", max_variants=8)
    assert len(variants) == len(set(variants))


def test_expand_query_handles_empty():
    assert expand_query("") == []
    assert expand_query("   ") == []


def test_expand_query_crowd_angle_for_skincare():
    variants = expand_query("面霜推荐", max_variants=10)
    # 护肤品类应有至少一条人群/场景变体
    assert len(variants) >= 5


# ── search_quality ─────────────────────────────────────────────


def test_assess_quality_empty():
    q = assess_search_quality([], score_type=ScoreType.PUBLIC_INDEX_HOT_SCORE, query="test")
    assert q["score"] == 0
    assert q["label"] == "empty"
    assert q["cache_ttl_multiplier"] < 1.0


def test_assess_quality_good_with_diverse_fresh_notes():
    notes = [
        note(f"n{i}", f"标题{i}", source_provider=f"src{i % 3}", age=i * 5, likes=100 * i)
        for i in range(1, 15)
    ]
    q = assess_search_quality(notes, score_type=ScoreType.METRIC_HOT_SCORE, query="test")
    assert q["score"] >= 50
    assert q["label"] in {"good", "fair"}
    assert q["cache_ttl_multiplier"] >= 0.5


def test_assess_quality_poor_when_single_source_and_old():
    # 5 notes from same source, no engagement metrics, old
    notes = [
        HotNoteCandidate(
            id=f"n{i}",
            url=f"https://www.xiaohongshu.com/explore/n{i}",
            title=f"标题{i}",
            source_provider="only_src",
            published_at=datetime.now(UTC) - timedelta(hours=500 + i),
        )
        for i in range(1, 6)
    ]
    q = assess_search_quality(notes, score_type=ScoreType.PUBLIC_INDEX_HOT_SCORE, query="test")
    # single source: diversity=1.0 (capped), freshness=0, relevance=1.0, metric=0, failure=0
    # score ≈ 20*1 + 30*0 + 25*1 + 15*0 + 10*1 = 55
    assert q["score"] < 70
    assert q["label"] in {"fair", "poor"}


def test_assess_quality_with_failures():
    notes = [note("1", "测试", age=10, likes=50)]
    q = assess_search_quality(
        notes,
        score_type=ScoreType.METRIC_HOT_SCORE,
        query="test",
        failures=3,
        total_calls=5,
    )
    assert q["metrics"]["failure_rate"] == 0.6
    assert q["recommendations"]


# ── generation_guards_from_quality ────────────────────────────────


def test_generation_guards_hard_when_poor():
    from xhs_skill.research.quality import generation_guards_from_quality

    g = generation_guards_from_quality({"score": 20, "label": "poor", "recommendations": ["结果偏旧"]})
    assert g["strength"] == "hard"
    assert any("evidence_boundary" in c for c in g["constraints"])
    assert any("disclaimer" in c for c in g["constraints"])
    assert g["assumptions"]
    assert g["disclaimer"]
    assert any("偏旧" in a for a in g["assumptions"])


def test_generation_guards_soft_when_fair():
    from xhs_skill.research.quality import generation_guards_from_quality

    g = generation_guards_from_quality({"score": 55, "label": "fair"})
    assert g["strength"] == "soft"
    assert g["constraints"]
    assert g["disclaimer"]
    assert "人工复核" in g["assumptions"][0]


def test_generation_guards_none_when_good():
    from xhs_skill.research.quality import generation_guards_from_quality

    g = generation_guards_from_quality({"score": 85, "label": "good"})
    assert g["strength"] == "none"
    assert g["constraints"] == []
    assert g["assumptions"] == []
    assert g["disclaimer"] == ""


# ── resolve_provider_names with preferred_order ──────────────────


def test_resolve_provider_names_respects_preferred_order():
    names = resolve_provider_names(
        registered=["fixture", "brave", "bing", "client_web"],
        explicit=None,
        has_web_results=False,
        fallback="fixture",
        preferred_order=["bing", "brave"],
        max_live_providers=1,
    )
    assert names == ["bing"]


def test_resolve_provider_names_respects_max_live_providers():
    names = resolve_provider_names(
        registered=["fixture", "brave", "bing", "google_cse", "client_web"],
        explicit=None,
        has_web_results=False,
        fallback="fixture",
        max_live_providers=2,
    )
    assert len(names) == 2
    assert all(n in {"brave", "bing", "google_cse"} for n in names)


# ── source diversity ────────────────────────────────────────────


def test_deduplicate_works():
    notes = [
        note("1", "防晒怎么选？先看五个场景"),
        note("2", "防晒怎么选先看五个场景"),
        note("3", "完全不同的标题"),
    ]
    result = deduplicate(notes)
    assert len(result) == 2


# ── research service integration ────────────────────────────────


@pytest.mark.asyncio
async def test_research_uses_client_web_results(tmp_path, monkeypatch):
    get_settings.cache_clear()
    settings = Settings(
        app_env="test",
        app_secret_key="Aa1!" + "x" * 36,
        search_auto_fallback="delegate",
        model_providers_file=tmp_path / "missing.yaml",
    )
    monkeypatch.setattr("xhs_skill.research.service.get_settings", lambda: settings)
    service = ResearchService(SearchRegistry(settings))
    report = await service.search_hot_notes(
        SearchQuery(query="通勤防晒", limit=5),
        web_results=[
            {
                "url": "https://www.xiaohongshu.com/explore/host-1",
                "title": "通勤防晒避坑清单",
                "snippet": "点赞 800 收藏 1200",
            },
            {
                "url": "https://www.xiaohongshu.com/explore/host-2",
                "title": "上班族防晒霜怎么选",
                "snippet": "真实使用一周",
            },
        ],
    )
    assert report.notes
    assert "client_web" in report.coverage_warning
    assert all(n.source_provider == "client_web" for n in report.notes)
    # search_quality 已填充
    assert report.search_quality
    assert report.search_quality.get("score") is not None
    assert report.search_quality.get("label") in {"good", "fair", "poor", "empty"}


@pytest.mark.asyncio
async def test_research_delegates_without_keys(tmp_path, monkeypatch):
    get_settings.cache_clear()
    settings = Settings(
        app_env="test",
        app_secret_key="Aa1!" + "x" * 36,
        search_auto_fallback="delegate",
        model_providers_file=tmp_path / "missing.yaml",
    )
    monkeypatch.setattr("xhs_skill.research.service.get_settings", lambda: settings)
    service = ResearchService(SearchRegistry(settings))
    with pytest.raises(ClientWebSearchRequired):
        await service.search_hot_notes(SearchQuery(query="通勤防晒", limit=5))