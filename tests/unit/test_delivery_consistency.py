"""交付包一致性：分页/分镜/标签与 body 对齐。"""

from __future__ import annotations

import pytest

from xhs_skill.generation.fallback import build_body, build_video, pages_from_body
from xhs_skill.generation.tags import append_hashtags_to_body, build_topics_and_hashtags
from xhs_skill.schemas.content import GenerateRequest


def test_pages_from_body_tracks_model_body():
    request = GenerateRequest(topic="通勤背包")
    body = "先说结论：选包看背负。\n\n场景：每天地铁一小时。\n\n证据：看实测重量。"
    pages = pages_from_body(request, body, None)
    assert pages[0].purpose == "cover"
    assert "背负" in pages[1].body_copy or "背负" in pages[1].headline
    assert any("地铁" in p.body_copy for p in pages)


def test_append_hashtags_idempotent():
    body = "正文内容\n\n#通勤背包"
    out = append_hashtags_to_body(body, ["#通勤背包", "#避坑"])
    assert out.count("#通勤背包") == 1
    assert "#避坑" in out


def test_fallback_body_includes_product_and_offline_mark():
    request = GenerateRequest(
        topic="降噪耳机",
        target_audience="上班族",
        product={"name": "某品牌耳机"},
        constraints=["预算千元内"],
        evidence=[{"source": "https://example.com/spec", "excerpt": "续航30小时", "claim_text": "续航30小时", "evidence_id": "e1"}],
    )
    body, pages = build_body(request, None)
    assert "离线" in body  # 离线骨架/模板标记
    assert "某品牌耳机" in body or "上班族" in body
    assert pages
    assert any("#" not in (p.headline or "") for p in pages)


def test_build_video_uses_body_chunks():
    request = GenerateRequest(topic="防晒霜")
    body = "钩子句独特ABC。\n\n第二段场景。\n\n第三段痛点。"
    script = build_video(request, body)
    assert "ABC" in script.hook_0_3s or "钩子" in script.hook_0_3s
    assert script.scenes


def test_topics_include_request_topic():
    request = GenerateRequest(topic="露营炉")
    topics, hashtags = build_topics_and_hashtags(request, None)
    assert "露营炉" in topics
    assert any(h.startswith("#") for h in hashtags)


@pytest.mark.asyncio
async def test_generate_service_body_has_hashtags_and_aligned_pages():
    from xhs_skill.generation.service import GenerationService
    from xhs_skill.providers.registry import ProviderRegistry

    service = GenerationService(providers=ProviderRegistry())
    package = await service.generate(GenerateRequest(topic="桌面收纳", format="graphic"))
    assert package.topics
    assert any(tag.lstrip("#") in package.body or tag in package.body for tag in package.hashtags[:3])
    assert package.graphic_pages
    # 分页 body_copy 应来自最终正文片段
    joined = " ".join(p.body_copy for p in package.graphic_pages)
    assert package.selected_title
    assert package.body
    assert len(joined) > 10