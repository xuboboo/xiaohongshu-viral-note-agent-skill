"""全链路创作者能力：brief / 钩子 / 就绪分 / 声线 / 发后一跳。"""

from __future__ import annotations

import pytest

from xhs_skill.generation.brief import build_content_brief
from xhs_skill.generation.hooks import expand_title_hooks, pick_pinned_comment
from xhs_skill.generation.keyword_seo import build_keyword_map
from xhs_skill.generation.quality_score import score_delivery_package
from xhs_skill.generation.voice import apply_voice_to_text, voice_constraints
from xhs_skill.operations.publish_timing import (
    best_publish_windows,
    calendar_topics_from_retrospective,
    generate_request_from_suggestion,
)
from xhs_skill.operations.retrospective import build_retrospective, enrich_retrospective_dict
from xhs_skill.operations.models import PublishedMetrics
from xhs_skill.schemas.content import DeliveryPackage, GenerateRequest


def test_content_brief_has_must_cover():
    brief = build_content_brief(
        GenerateRequest(topic="露营炉", target_audience="新手", product={"name": "气炉A"})
    )
    assert brief["topic"] == "露营炉"
    assert brief["must_cover"]
    assert "编造亲测经历" in brief["forbidden"]


def test_title_hooks_diverse():
    titles = expand_title_hooks(GenerateRequest(topic="降噪耳机", candidate_count=8))
    assert len(titles) >= 6
    assert len({t.title for t in titles}) >= 6


def test_keyword_map_has_long_tail():
    km = build_keyword_map(GenerateRequest(topic="防晒霜", target_audience="通勤党"))
    assert km["primary_keyword"] == "防晒霜"
    assert any("怎么选" in x for x in km["secondary_keywords"])


def test_voice_removes_banned():
    req = GenerateRequest(topic="包", brand_voice={"banned_phrases": ["闭眼冲"], "tone": "克制"})
    text, notes = apply_voice_to_text("真的闭眼冲就完了", req)
    assert "闭眼冲" not in text
    assert notes
    assert voice_constraints(req)["tone"] == "克制"


def test_readiness_score_on_package():
    pkg = DeliveryPackage(
        task_id="t",
        trace_id="r",
        selected_title="降噪耳机怎么选",
        body="降噪耳机怎么选\n\n先说结论：按通勤场景判断。\n\n"
        + "具体场景和边界。" * 5
        + "\n\n#降噪耳机",
        content_hash="h",
        cta="欢迎补充场景",
        pinned_comment="你最在意续航还是降噪？",
        topics=["降噪耳机"],
        hashtags=["#降噪耳机"],
        compliance_report={"passed": True},
        originality_report={"publication_allowed": True},
        keyword_map={"secondary_keywords": ["降噪耳机怎么选"]},
        publication_status="HUMAN_REVIEW_REQUIRED",
    )
    score = score_delivery_package(pkg)
    assert score["overall_score"] >= 60
    assert "dimensions" in score


def test_publish_windows_default():
    windows = best_publish_windows(None)
    assert windows["hours_local"]
    assert "suggestion" in windows


def test_suggestion_to_generate_payload():
    payload = generate_request_from_suggestion(
        {"topic": "露营炉避坑版", "angle": "失败边界", "reason": "补边界"}
    )
    assert payload["topic"] == "露营炉避坑版"
    assert payload["suggested_topic"] == "露营炉避坑版"


def test_retro_enrich_calendar_topics():
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
    data = enrich_retrospective_dict(retro.model_dump(mode="json"))
    assert data["calendar_topics"]
    assert data["calendar_payload"]["fallback_topics"]
    assert data["next_note_suggestions"][0].get("generate_payload", {}).get("topic")


@pytest.mark.asyncio
async def test_generate_includes_readiness_and_brief():
    from xhs_skill.generation.service import GenerationService
    from xhs_skill.providers.registry import ProviderRegistry

    service = GenerationService(providers=ProviderRegistry())
    package = await service.generate(
        GenerateRequest(
            topic="桌面收纳",
            brand_voice={"banned_phrases": ["绝绝子"]},
            target_audience="租房党",
        )
    )
    assert package.quality_report.get("content_brief")
    assert package.quality_report.get("readiness")
    assert package.keyword_map.get("primary_keyword") == "桌面收纳"
    assert package.pinned_comment


def test_pinned_comment_rotates():
    req = GenerateRequest(topic="包")
    a = pick_pinned_comment(req, 0)
    b = pick_pinned_comment(req, 1)
    assert a != b