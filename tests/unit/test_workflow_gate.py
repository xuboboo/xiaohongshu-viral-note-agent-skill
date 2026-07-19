"""编排层质量门控。"""
import pytest

from xhs_skill.orchestrator.workflow import ContentWorkflow, _workflow_quality_gate
from xhs_skill.schemas.content import DeliveryPackage, GenerateRequest


def test_quality_gate_ready_when_clean():
    package = DeliveryPackage(
        task_id="t",
        trace_id="tr",
        selected_title="标题",
        body="正文",
        topics=["空气炸锅"],
        hashtags=["#空气炸锅"],
        cover_options=[],
        content_hash="abc",
        publication_status="HUMAN_REVIEW_REQUIRED",
        originality_report={"publication_allowed": True},
        compliance_report={"passed": True},
        quality_report={},
    )
    gate = _workflow_quality_gate(package)
    assert gate["blocked"] is False
    assert gate["ready_for_draft"] is True


def test_quality_gate_blocks_on_compliance():
    package = DeliveryPackage(
        task_id="t",
        trace_id="tr",
        selected_title="标题",
        body="正文",
        content_hash="abc",
        publication_status="HUMAN_REVIEW_REQUIRED",
        originality_report={"publication_allowed": True},
        compliance_report={"passed": False},
        quality_report={},
    )
    gate = _workflow_quality_gate(package)
    assert gate["blocked"] is True
    assert gate["recommendations"]


@pytest.mark.asyncio
async def test_workflow_attaches_gate_meta():
    wf = ContentWorkflow()
    package = await wf.run(
        GenerateRequest(topic="空气炸锅", research_current_trends=False),
        tenant_id="local",
    )
    assert "workflow" in package.quality_report
    assert "gate" in package.quality_report["workflow"]
    assert "diagnose" in package.quality_report["workflow"]
    assert package.quality_report["workflow"]["research"]["ran"] is False
    assert package.topics or package.hashtags


@pytest.mark.asyncio
async def test_workflow_rewrite_suggestion_on_hype():
    from xhs_skill.generation.service import GenerationService
    from xhs_skill.schemas.content import DeliveryPackage

    class FakeGen(GenerationService):
        async def generate(self, request, report=None, *, tenant_id="local"):
            return DeliveryPackage(
                task_id="t",
                trace_id="tr",
                selected_title="标题",
                body="宝子们谁懂啊，闭眼冲！",
                topics=["t"],
                hashtags=["#t"],
                content_hash="h",
                publication_status="HUMAN_REVIEW_REQUIRED",
                originality_report={"publication_allowed": True},
                compliance_report={"passed": True, "ai_style": {"ai_style_score": 60, "detected_patterns": ["宝子们"], "rewrite_actions": ["删除套话"]}},
                quality_report={},
            )

        async def rewrite(self, body, **kwargs):
            return {
                "revised": "建议先核对自己的使用需求。",
                "changes": [{"rule_id": "empty_hype"}],
                "publication_status": "REVIEW",
                "quality_report": {"change_count": 1},
            }

    wf = ContentWorkflow(generation=FakeGen())
    package = await wf.run(
        GenerateRequest(topic="防晒", research_current_trends=False),
        tenant_id="local",
    )
    suggestion = package.quality_report["workflow"]["rewrite_suggestion"]
    assert suggestion is not None
    assert suggestion["applied"] is False
    assert suggestion["change_count"] == 1