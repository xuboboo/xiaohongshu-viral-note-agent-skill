import pytest

from xhs_skill.orchestrator import ContentWorkflow
from xhs_skill.schemas.content import GenerateRequest


@pytest.mark.asyncio
async def test_fixture_pipeline_produces_complete_package():
    package = await ContentWorkflow().run(
        GenerateRequest(topic="通勤防晒", research_current_trends=True),
        search_providers=["fixture"],
    )
    assert package.selected_title
    assert package.body
    assert package.graphic_pages
    assert package.content_hash
    assert (
        "公开" in package.research_summary["coverage_warning"]
        or "授权" in package.research_summary["coverage_warning"]
    )
