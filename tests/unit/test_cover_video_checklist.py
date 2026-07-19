"""封面联动 / 口播时长 / 清单分页。"""

from __future__ import annotations

import pytest

from xhs_skill.generation.checklist_pages import (
    checklist_pages,
    ensure_checkbox_body,
    extract_checklist_items,
)
from xhs_skill.generation.covers import build_cover_options
from xhs_skill.generation.fallback import build_body, build_video, pages_from_body
from xhs_skill.generation.outline import build_content_outline
from xhs_skill.generation.video_storyboard import build_video_script, normalize_video_duration
from xhs_skill.schemas.content import GenerateRequest


def test_cover_reflects_note_style():
    req = GenerateRequest(topic="降噪耳机", note_style="avoid_pitfall")
    outline = build_content_outline(req, None, note_style="avoid_pitfall")
    covers = build_cover_options(req, selected_title="降噪耳机避坑", outline=outline)
    assert covers
    tags = " ".join(c.supporting_tag for c in covers)
    subs = " ".join(c.subheadline for c in covers)
    assert "避坑" in tags or "避坑" in subs or "雷" in subs


def test_video_duration_templates():
    req = GenerateRequest(topic="露营炉", format="video", video_duration_seconds=15)
    body = "钩子开场。\n\n场景说明。\n\n证据要点。\n\n结尾互动。"
    script = build_video(req, body, duration_seconds=15)
    assert script.duration_seconds == 15
    assert script.scenes
    assert script.scenes[-1].end == 15
    assert normalize_video_duration(50) == 45
    assert normalize_video_duration(12) == 15


def test_video_60s_has_more_scenes():
    req = GenerateRequest(topic="防晒霜")
    s15 = build_video_script(req, "a\n\nb\n\nc", duration_seconds=15)
    s60 = build_video_script(req, "a\n\nb\n\nc\n\nd", duration_seconds=60)
    assert len(s60.scenes) > len(s15.scenes)


def test_checklist_extract_and_pages():
    body = "开场\n\n【核对清单】\n□ 看续航\n□ 看降噪\n□ 看佩戴\n□ 看售后"
    items = extract_checklist_items(body)
    assert len(items) >= 3
    req = GenerateRequest(topic="耳机", note_style="checklist")
    pages = checklist_pages(req, body, items_per_page=2)
    assert pages[0].purpose == "cover"
    assert any(p.purpose == "checklist" for p in pages)
    assert any("□" in p.body_copy for p in pages if p.purpose == "checklist")


def test_ensure_checkbox_appends_when_missing():
    body = "只有一段话没有清单。"
    out = ensure_checkbox_body(body, items=["场景", "预算", "边界"])
    assert "□ 场景" in out
    assert "核对清单" in out


def test_pages_from_body_checklist_mode():
    req = GenerateRequest(topic="收纳", note_style="checklist")
    body, pages = build_body(req, None)
    assert "□" in body
    assert any(p.purpose == "checklist" for p in pages)


@pytest.mark.asyncio
async def test_generate_video_duration_and_checklist():
    from xhs_skill.generation.service import GenerationService
    from xhs_skill.providers.registry import ProviderRegistry

    svc = GenerationService(providers=ProviderRegistry())
    video = await svc.generate(
        GenerateRequest(
            topic="咖啡机",
            format="video",
            video_duration_seconds=30,
            note_style="review",
        )
    )
    assert video.video_script is not None
    assert video.video_script.duration_seconds == 30
    assert len(video.video_script.scenes) >= 3

    check = await svc.generate(
        GenerateRequest(topic="露营装备", note_style="checklist", format="graphic")
    )
    assert any(p.purpose == "checklist" for p in check.graphic_pages)
    assert check.cover_options
    assert "避" in check.cover_options[0].supporting_tag or check.cover_options[0].headline