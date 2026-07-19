"""GenerationService.rewrite 集成门禁：originality + references。"""
from __future__ import annotations

import pytest

from xhs_skill.generation.service import GenerationService
from xhs_skill.schemas.content import GenerateRequest


@pytest.mark.asyncio
async def test_rewrite_includes_originality_report():
    service = GenerationService()
    result = await service.rewrite(
        body="宝子们谁懂啊，这个防晒绝绝子，闭眼冲！",
        title="防晒怎么选",
        references=["这是一篇完全无关的参考文案，用于原创性对照。"],
    )
    assert "revised" in result
    assert "宝子们谁懂啊" not in result["revised"]
    assert "originality" in result["quality_report"]
    assert "publication_allowed" in result["quality_report"]["originality"]
    assert result["quality_report"]["reference_count"] == 1
    assert result["quality_report"]["rewrite_path"] in {"provider", "deterministic_rules"}


@pytest.mark.asyncio
async def test_rewrite_blocks_near_copy():
    service = GenerationService()
    source = "这是一段足够长的原文用于检测洗稿风险，包含具体场景与参数描述，方便相似度门禁触发。"
    result = await service.rewrite(body=source, references=[source])
    assert result["quality_report"]["originality"]["publication_allowed"] is False
    assert result["publication_status"] == "BLOCKED"


@pytest.mark.asyncio
async def test_generate_package_has_topics_and_covers():
    service = GenerationService()
    package = await service.generate(
        GenerateRequest(topic="空气炸锅", research_current_trends=False),
    )
    assert package.topics
    assert package.hashtags
    assert len(package.cover_options) >= 2