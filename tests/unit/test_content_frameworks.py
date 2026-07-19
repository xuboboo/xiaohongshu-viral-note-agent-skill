"""内容框架与大纲能力。"""

from __future__ import annotations

import pytest

from xhs_skill.generation.fallback import build_body
from xhs_skill.generation.frameworks import (
    NarrativeFramework,
    NoteStyle,
    build_framework_meta,
    resolve_framework,
    resolve_note_style,
)
from xhs_skill.generation.outline import build_content_outline, render_body_from_outline
from xhs_skill.schemas.content import GenerateRequest


def test_resolve_style_aliases():
    assert resolve_note_style("避坑") == NoteStyle.AVOID_PITFALL
    assert resolve_note_style("review") == NoteStyle.REVIEW
    assert resolve_framework("aida", NoteStyle.SEEDING) == NarrativeFramework.AIDA
    assert resolve_framework("auto", NoteStyle.AVOID_PITFALL) == NarrativeFramework.PAS


def test_framework_meta_stages():
    meta = build_framework_meta(note_style="checklist", narrative_framework="scqa")
    assert meta["note_style"] == "checklist"
    assert meta["narrative_framework"] == "scqa"
    assert len(meta["stages"]) >= 3


def test_outline_has_hook_and_sections():
    req = GenerateRequest(topic="露营炉", note_style="avoid_pitfall", target_audience="新手")
    outline = build_content_outline(req, None)
    assert outline["opening_hook"]
    assert outline["closing_cta"]
    assert outline["emotion_arc"]
    assert len(outline["sections"]) >= 3
    assert outline["note_style"] == "avoid_pitfall"


def test_different_styles_produce_different_bodies():
    base = dict(topic="降噪耳机", target_audience="通勤党")
    b1, _ = build_body(GenerateRequest(**base, note_style="review"), None)
    b2, _ = build_body(GenerateRequest(**base, note_style="avoid_pitfall"), None)
    b3, _ = build_body(GenerateRequest(**base, note_style="checklist", narrative_framework="aida"), None)
    assert "测评" in b1 or "结构" in b1 or "【" in b1
    assert b1 != b2 or b2 != b3
    assert "【" in b2  # framework section markers


def test_render_outline_includes_cta():
    req = GenerateRequest(topic="防晒霜")
    outline = build_content_outline(req, None, note_style="seeding", narrative_framework="aida")
    body = render_body_from_outline(req, outline)
    assert outline["closing_cta"][:8] in body or "场景" in body


@pytest.mark.asyncio
async def test_generate_attaches_outline():
    from xhs_skill.generation.service import GenerationService
    from xhs_skill.providers.registry import ProviderRegistry

    svc = GenerationService(providers=ProviderRegistry())
    pkg = await svc.generate(
        GenerateRequest(topic="桌面收纳", note_style="checklist", narrative_framework="pas")
    )
    outline = pkg.quality_report.get("content_outline") or {}
    assert outline.get("narrative_framework") == "pas"
    assert outline.get("sections")
    assert pkg.strategy.get("outline")