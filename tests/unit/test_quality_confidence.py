"""质量置信注记与 A2A 能力测试。"""

from __future__ import annotations

import pytest

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.research.quality import generation_guards_from_quality
from xhs_skill.research.search_memory import SearchQualityMemory
from xhs_skill.research.service import ResearchService
from xhs_skill.schemas.research import SearchQuery
from xhs_skill.search.registry import SearchRegistry


@pytest.mark.asyncio
async def test_delivery_package_carries_search_quality_report(tmp_path, monkeypatch):
    get_settings.cache_clear()
    settings = Settings(
        app_env="test",
        app_secret_key="Aa1!" + "x" * 36,
        search_auto_fallback="delegate",
        model_providers_file=tmp_path / "missing.yaml",
        enterprise_enabled=False,
        enterprise_policy_enforcement=False,
    )
    monkeypatch.setattr("xhs_skill.research.service.get_settings", lambda: settings)
    mem = SearchQualityMemory(tmp_path / "sq")
    service = ResearchService(SearchRegistry(settings), quality_memory=mem)

    report = await service.search_hot_notes(
        SearchQuery(query="通勤防晒", limit=5),
        web_results=[
            {
                "url": "https://www.xiaohongshu.com/explore/r1",
                "title": "通勤防晒避坑清单",
                "snippet": "点赞 800 收藏 1200 适合上班族",
            },
            {
                "url": "https://www.xiaohongshu.com/explore/r2",
                "title": "上班族防晒霜怎么选",
                "snippet": "真实使用一周 边界说明",
            },
        ],
    )
    sq = report.search_quality or {}
    assert sq.get("score") is not None
    assert sq.get("label") in {"good", "fair", "poor", "empty"}
    assert sq.get("strategy") is not None
    assert sq.get("delta") is not None


def test_a2a_agent_card_has_search_quality_capability(auth_headers):
    from fastapi.testclient import TestClient
    from xhs_skill.api.app import create_app

    client = TestClient(create_app())
    card = client.get("/.well-known/agent-card.json", headers=auth_headers)
    assert card.status_code == 200
    body = card.json()
    caps = body.get("capabilities") or {}
    sq = caps.get("search_quality") or {}
    assert sq.get("adaptive") is True
    assert isinstance(sq.get("features"), list) and len(sq["features"]) >= 3
    assert isinstance(sq.get("ux_fields"), list)
    assert any("score" in f for f in sq["ux_fields"])
    assert any("guards" in f for f in sq["ux_fields"])
    assert "自适应" in body.get("description") or "quality" in body.get("description")


def test_generation_guards_none_when_quality_good():
    g = generation_guards_from_quality({"score": 90, "label": "good"})
    assert g["strength"] == "none"
    assert g["constraints"] == []


def test_generation_guards_fair_when_score_default():
    # None → score defaults to 50, label to "fair" → soft
    g = generation_guards_from_quality(None)
    assert g["strength"] == "soft"
    assert g["constraints"]
    assert g["disclaimer"]