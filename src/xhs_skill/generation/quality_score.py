"""交付就绪分：把结构/合规/原创/可发现性合成可解释记分卡。"""

from __future__ import annotations

from typing import Any

from xhs_skill.generation.diagnose_structure import structure_checks
from xhs_skill.schemas.content import DeliveryPackage


def score_delivery_package(package: DeliveryPackage) -> dict[str, Any]:
    """0–100 就绪分 + 维度分 + 阻断项。不替代门禁布尔。"""
    structure = structure_checks(package=package)
    checks = structure.get("checks") or {}

    structure_score = int(100 * sum(1 for v in checks.values() if v) / max(1, len(checks)))
    compliance = package.compliance_report or {}
    originality = package.originality_report or {}
    compliance_score = 100 if compliance.get("passed", False) else 35
    originality_score = 100 if originality.get("publication_allowed", False) else 40

    discover = 40
    if package.topics or package.hashtags:
        discover += 25
    if package.keyword_map.get("secondary_keywords"):
        discover += 15
    if package.cta and package.pinned_comment:
        discover += 20
    discover = min(100, discover)

    claim_penalty = min(40, 10 * sum(1 for c in package.claims if not c.verified))
    fact_score = max(0, 100 - claim_penalty)

    # 权重：结构 25 合规 25 原创 20 可发现 15 事实 15
    overall = int(
        structure_score * 0.25
        + compliance_score * 0.25
        + originality_score * 0.20
        + discover * 0.15
        + fact_score * 0.15
    )

    blockers: list[str] = []
    if package.publication_status == "BLOCKED":
        blockers.append("publication_status=BLOCKED")
    if not compliance.get("passed", False):
        blockers.append("compliance_failed")
    if not originality.get("publication_allowed", False):
        blockers.append("originality_blocked")
    unverified = [c.id for c in package.claims if not c.verified]
    if unverified:
        blockers.append(f"unverified_claims:{len(unverified)}")

    ready = overall >= 70 and not blockers and package.publication_status != "BLOCKED"

    return {
        "overall_score": overall,
        "ready_for_human_review": ready and package.publication_status != "BLOCKED",
        "ready_for_publish_gate": ready,  # 仍需审批 token；仅表示内容侧就绪
        "dimensions": {
            "structure": structure_score,
            "compliance": compliance_score,
            "originality": originality_score,
            "discoverability": discover,
            "factuality": fact_score,
        },
        "blockers": blockers,
        "recommended_fixes": structure.get("recommended_fixes") or [],
        "structure_checks": checks,
    }