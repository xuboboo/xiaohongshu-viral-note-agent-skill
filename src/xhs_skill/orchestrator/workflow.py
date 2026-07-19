"""Content plane 编排：研究 → 生成 → diagnose/rewrite 建议 → 质量门控。

职责边界：
- 不碰 publish token / 登录
- 不在此重跑 enterprise 审批
- 输出仍是 DeliveryPackage；诊断建议写入 quality_report.workflow
"""
from __future__ import annotations

from typing import Any

from xhs_skill.generation import GenerationService
from xhs_skill.research import ResearchService
from xhs_skill.schemas.content import DeliveryPackage, GenerateRequest
from xhs_skill.schemas.research import SearchQuery
from xhs_skill.verifiers import ai_style_report, check_text


def _workflow_quality_gate(package: DeliveryPackage) -> dict[str, Any]:
    """对交付包做轻量端到端门控摘要（不二次调用模型）。"""
    originality = package.originality_report or {}
    compliance = package.compliance_report or {}
    unverified = list(package.quality_report.get("unverified_claim_ids") or [])
    publication_allowed = bool(originality.get("publication_allowed", True))
    compliance_passed = bool(compliance.get("passed", True))
    has_topics = bool(package.topics or package.hashtags)
    has_covers = len(package.cover_options) >= 1
    blocked = (
        package.publication_status == "BLOCKED"
        or not publication_allowed
        or not compliance_passed
        or bool(unverified)
    )
    recommendations: list[str] = []
    if not compliance_passed:
        recommendations.append("修复合规 findings 后再进入发布草稿")
    if not publication_allowed:
        recommendations.append("降低与参考笔记的相似表达，补充原创场景细节")
    if unverified:
        recommendations.append("为未验证 claim 补充 evidence 或删除绝对化表述")
    if not has_topics:
        recommendations.append("补充 topics/hashtags 以提升发布可发现性")
    if not has_covers:
        recommendations.append("补充封面方案后再制作视觉素材")
    if package.publication_status == "HUMAN_REVIEW_REQUIRED":
        recommendations.append("人工预览标题/正文/商业披露/AI 标识")

    return {
        "blocked": blocked,
        "ready_for_draft": not blocked and has_topics,
        "checks": {
            "compliance_passed": compliance_passed,
            "originality_allowed": publication_allowed,
            "unverified_claims": len(unverified),
            "topics_present": has_topics,
            "cover_options": len(package.cover_options),
            "ranker": package.quality_report.get("ranker"),
        },
        "recommendations": recommendations[:8],
    }


def _diagnose_package(package: DeliveryPackage) -> dict[str, Any]:
    """同步 diagnose 摘要：复用已有门禁结果 + AI 风格 + 结构检查。"""
    from xhs_skill.generation.diagnose_structure import structure_checks

    body = package.body or ""
    title = package.selected_title or ""
    compliance = package.compliance_report or check_text(f"{title}\n{body}")
    originality = package.originality_report or {}
    ai_style = (compliance.get("ai_style") if isinstance(compliance, dict) else None) or ai_style_report(
        body
    )
    rewrite_actions = list(ai_style.get("rewrite_actions") or [])
    if ai_style.get("detected_patterns"):
        rewrite_actions.append("调用 rewrite 管线删除套话并补场景边界")
    if not originality.get("publication_allowed", True):
        rewrite_actions.append("降低与研究样本的字面/语义重合后再发布")
    structure = structure_checks(package=package)
    fixes = list(structure.get("recommended_fixes") or [])
    fixes.extend(rewrite_actions[:3])
    return {
        "compliance_passed": bool(compliance.get("passed", True)),
        "originality_allowed": bool(originality.get("publication_allowed", True)),
        "ai_style_score": ai_style.get("ai_style_score"),
        "detected_patterns": ai_style.get("detected_patterns") or [],
        "rewrite_actions": rewrite_actions[:8],
        "structure_checks": structure.get("checks") or {},
        "recommended_fixes": fixes[:8]
        or [
            "增加具体场景、限制条件和不适合人群",
            "删除无法验证的数据和效果承诺",
        ],
    }


class ContentWorkflow:
    def __init__(
        self,
        research: ResearchService | None = None,
        generation: GenerationService | None = None,
    ) -> None:
        self.research = research or ResearchService()
        self.generation = generation or GenerationService()

    async def run(
        self,
        request: GenerateRequest,
        *,
        search_providers: list[str] | None = None,
        tenant_id: str = "local",
        web_results: list[dict[str, Any]] | None = None,
        auto_rewrite_suggestion: bool = True,
    ) -> DeliveryPackage:
        report = None
        research_meta: dict[str, Any] = {"ran": False}
        if request.research_current_trends:
            hits = web_results if web_results is not None else request.web_results
            report = await self.research.search_hot_notes(
                SearchQuery(query=request.topic, time_range="7d", limit=30),
                providers=search_providers,
                web_results=hits or None,
            )
            research_meta = {
                "ran": True,
                "notes": len(report.notes),
                "mechanisms": len(report.mechanisms),
                "coverage_warning": report.coverage_warning,
                "search_quality": {
                    "score": (report.search_quality or {}).get("score"),
                    "label": (report.search_quality or {}).get("label"),
                    "delta": (report.search_quality or {}).get("delta"),
                    "recommendations": (report.search_quality or {}).get("recommendations") or [],
                },
            }
        package = await self.generation.generate(request, report, tenant_id=tenant_id)
        diagnose = _diagnose_package(package)
        rewrite_suggestion: dict[str, Any] | None = None
        # 仅在 AI 味高或有明确 rewrite_actions 时跑确定性/模型改写建议（不覆盖原 body）
        needs_rewrite = bool(diagnose.get("rewrite_actions")) or int(
            diagnose.get("ai_style_score") or 0
        ) >= 36
        if auto_rewrite_suggestion and needs_rewrite:
            references = [
                note.body or note.snippet or note.title
                for note in (report.notes if report else [])
            ][:20]
            rewrite_suggestion = await self.generation.rewrite(
                body=package.body,
                title=package.selected_title,
                commercial_status=str(
                    request.commercial_status.value
                    if hasattr(request.commercial_status, "value")
                    else request.commercial_status
                ),
                constraints=list(request.constraints or []),
                references=references,
                tenant_id=tenant_id,
            )
            # 建议态：不自动替换 package.body，仅挂旁路结果
            rewrite_suggestion = {
                "applied": False,
                "reason": "suggestion_only",
                "publication_status": rewrite_suggestion.get("publication_status"),
                "change_count": rewrite_suggestion.get("quality_report", {}).get(
                    "change_count"
                ),
                "revised_preview": (rewrite_suggestion.get("revised") or "")[:500],
                "changes": (rewrite_suggestion.get("changes") or [])[:10],
                "quality_report": rewrite_suggestion.get("quality_report"),
            }

        gate = _workflow_quality_gate(package)
        # 合并 diagnose 建议进 gate.recommendations
        for item in diagnose.get("recommended_fixes") or []:
            if item not in gate["recommendations"]:
                gate["recommendations"].append(item)
        gate["recommendations"] = gate["recommendations"][:10]

        package.quality_report = {
            **package.quality_report,
            "workflow": {
                "research": research_meta,
                "diagnose": diagnose,
                "rewrite_suggestion": rewrite_suggestion,
                "gate": gate,
            },
        }
        if gate["blocked"] and package.publication_status not in {"BLOCKED"}:
            package.publication_status = (
                "BLOCKED"
                if (
                    not gate["checks"]["compliance_passed"]
                    or not gate["checks"]["originality_allowed"]
                    or gate["checks"]["unverified_claims"] > 0
                )
                else package.publication_status
            )
        if gate["recommendations"]:
            existing = list(package.human_review_required or [])
            for item in gate["recommendations"]:
                if item not in existing:
                    existing.append(item)
            package.human_review_required = existing
        return package