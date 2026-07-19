from datetime import UTC, datetime, timedelta

import pytest

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.research.deduplicator import deduplicate
from xhs_skill.research.normalizer import canonicalize_url, parse_metric
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
        source_provider="test",
        published_at=datetime.now(UTC) - timedelta(hours=kwargs.pop("age", 12)),
        **kwargs,
    )


def test_canonicalize_url_removes_tracking():
    url = canonicalize_url("https://www.xiaohongshu.com/explore/1?utm_source=x&a=1#foo")
    assert url == "https://www.xiaohongshu.com/explore/1?a=1"


@pytest.mark.parametrize(
    ("raw", "expected"), [("1.2万", 12000), ("3k", 3000), (120, 120), (None, None)]
)
def test_parse_metric(raw, expected):
    assert parse_metric(raw) == expected


def test_deduplicate_semantic_near_duplicates():
    notes = [note("1", "防晒怎么选？先看五个场景"), note("2", "防晒怎么选先看五个场景")]
    assert len(deduplicate(notes)) == 1


def test_metric_ranking_is_labeled():
    score_type, ranked = rank_hot_notes(
        [note("1", "防晒实测", likes=100, saves=500), note("2", "防晒攻略", likes=50, saves=20)],
        "防晒",
    )
    assert score_type == ScoreType.METRIC_HOT_SCORE
    assert ranked[0].hot_score is not None


def test_public_ranking_is_labeled():
    score_type, _ = rank_hot_notes([note("1", "防晒实测")], "防晒")
    assert score_type == ScoreType.PUBLIC_INDEX_HOT_SCORE


def test_resolve_prefers_web_results_over_live_keys():
    names = resolve_provider_names(
        registered=["fixture", "brave", "client_web"],
        explicit=None,
        has_web_results=True,
        fallback="delegate",
        query="防晒",
    )
    assert names == ["client_web"]


def test_resolve_live_providers_when_configured():
    names = resolve_provider_names(
        registered=["fixture", "brave", "bing", "client_web"],
        explicit=None,
        has_web_results=False,
        fallback="delegate",
        query="防晒",
    )
    assert names == ["brave", "bing"]


def test_resolve_delegate_when_no_live_provider():
    with pytest.raises(ClientWebSearchRequired) as exc:
        resolve_provider_names(
            registered=["fixture", "client_web"],
            explicit=None,
            has_web_results=False,
            fallback="delegate",
            query="通勤防晒",
            limit=10,
        )
    payload = exc.value.to_payload()
    assert payload["status"] == "needs_web_search"
    assert payload["suggested_queries"]
    assert "web_results" in payload["instructions"]


def test_normalize_web_results_accepts_host_shapes():
    results = normalize_web_results(
        [
            {
                "link": "https://www.xiaohongshu.com/explore/abc",
                "name": "通勤防晒实测",
                "description": "点赞 1.2万 收藏 3000",
                "date": "2026-07-01",
            },
            {"url": "", "title": "skip empty"},
            "not-a-dict",  # type: ignore[list-item]
        ]
    )
    assert len(results) == 1
    assert results[0].source_provider == "client_web"
    assert results[0].title == "通勤防晒实测"


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
    assert all(note.source_provider == "client_web" for note in report.notes)


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
