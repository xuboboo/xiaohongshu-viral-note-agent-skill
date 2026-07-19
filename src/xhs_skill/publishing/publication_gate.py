"""发布前服务端重验：不信任客户端自报的 compliance/originality/claims.verified。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.intelligence.embeddings import EmbeddingProvider
from xhs_skill.schemas.content import CommercialStatus, DeliveryPackage
from xhs_skill.verifiers.ai_style import ai_style_report
from xhs_skill.verifiers.claims import extract_claims
from xhs_skill.verifiers.compliance import check_text
from xhs_skill.verifiers.originality import originality_report, originality_report_async


def evidence_from_package(package: DeliveryPackage) -> list[dict[str, Any]]:
    """从包内已有 evidence_refs 规范为 extract_claims 可消费的字典列表。

    不读取 claim.verified；证据是否仍绑定当前 claim 文本由 extract_claims 重算。
    """
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for claim in package.claims or []:
        claim_text = (claim.text or "").strip()
        for ref in claim.evidence_refs or []:
            evidence_id = str(ref.evidence_id or "").strip()
            if not evidence_id or evidence_id in seen:
                continue
            seen.add(evidence_id)
            items.append(
                {
                    "evidence_id": evidence_id,
                    "id": evidence_id,
                    "source": ref.source,
                    "excerpt": ref.excerpt,
                    "claim_text": claim_text,
                    "text": claim_text,
                    "locator": ref.locator,
                    "confidence": ref.confidence,
                    "valid_until": ref.valid_until,
                }
            )
    return items


def _commercial_status(package: DeliveryPackage) -> CommercialStatus:
    raw = (package.strategy or {}).get("commercial_status", CommercialStatus.NON_COMMERCIAL)
    if isinstance(raw, CommercialStatus):
        return raw
    try:
        return CommercialStatus(str(raw))
    except ValueError:
        return CommercialStatus.NON_COMMERCIAL


def _reference_texts(package: DeliveryPackage) -> list[str]:
    refs: list[str] = []
    for note in package.hot_notes or []:
        text = (note.body or note.snippet or note.title or "").strip()
        if text:
            refs.append(text)
    return refs


def _apply_gate_fields(
    package: DeliveryPackage,
    *,
    claims: list[Any],
    compliance: dict[str, Any],
    originality: dict[str, Any],
    ai_style: dict[str, Any],
    semantic_embeddings: str,
) -> DeliveryPackage:
    unverified = [claim for claim in claims if not claim.verified]
    blocked = (
        not bool(compliance.get("passed"))
        or not bool(originality.get("publication_allowed"))
        or bool(unverified)
    )
    status = "BLOCKED" if blocked else "HUMAN_REVIEW_REQUIRED"

    quality = dict(package.quality_report or {})
    quality["server_reverified"] = True
    quality["server_reverify"] = {
        "at": datetime.now(UTC).isoformat(),
        "semantic_embeddings": semantic_embeddings,
        "blocked": blocked,
        "unverified_claim_count": len(unverified),
    }
    quality["unverified_claim_ids"] = [claim.id for claim in unverified]
    quality["fact_review_required"] = bool(unverified)

    return package.model_copy(
        update={
            "claims": claims,
            "compliance_report": {**compliance, "ai_style": ai_style},
            "originality_report": originality,
            "quality_report": quality,
            "publication_status": status,
        }
    )


def _with_semantic_status(package: DeliveryPackage, semantic_embeddings: str) -> DeliveryPackage:
    """仅更新 server_reverify.semantic_embeddings，不重算门禁。"""
    quality = dict(package.quality_report or {})
    server = dict(quality.get("server_reverify") or {})
    server["semantic_embeddings"] = semantic_embeddings
    quality["server_reverify"] = server
    return package.model_copy(update={"quality_report": quality})


def reverify_package(
    package: DeliveryPackage,
    *,
    settings: Settings | None = None,
) -> DeliveryPackage:
    """用 title+body 重跑 claims / 合规 / 同步原创门禁，覆盖客户端报告字段。

    不修改 title/body/media；publication_status 仅能为 BLOCKED 或 HUMAN_REVIEW_REQUIRED。
    语义 embedding 在同步路径标记为 skipped_sync_gate（真正发布见 reverify_package_async）。
    """
    settings = settings or get_settings()
    title = package.selected_title or ""
    body = package.body or ""
    text = f"{title}\n{body}"

    claims = extract_claims(text, evidence_from_package(package))
    commercial = _commercial_status(package)
    compliance = check_text(text, commercial)
    originality = originality_report(body, _reference_texts(package), settings)
    ai_style = ai_style_report(body)

    return _apply_gate_fields(
        package,
        claims=claims,
        compliance=compliance,
        originality=originality,
        ai_style=ai_style,
        semantic_embeddings="skipped_sync_gate",
    )


async def reverify_package_async(
    package: DeliveryPackage,
    *,
    settings: Settings | None = None,
    embedder: EmbeddingProvider | None = None,
) -> DeliveryPackage:
    """在同步 reverify 基础上，有参考文本时跑语义 embedding 原创门禁。

    - create_draft / approve 可继续用同步 reverify_package（快路径）
    - publish `_preflight` 必须走本函数
    - embedding 失败不抛穿：标记 skipped_error_*，保留同步原创结果
    """
    settings = settings or get_settings()
    base = reverify_package(package, settings=settings)
    refs = _reference_texts(base)
    body = base.body or ""

    if not refs:
        return _with_semantic_status(base, "skipped_no_references")

    try:
        originality = await originality_report_async(
            body,
            refs,
            embedder=embedder,
            settings=settings,
        )
        semantic_status = "evaluated"
    except Exception as exc:  # noqa: BLE001 — embedding 可选，失败保留同步结果
        originality = dict(base.originality_report or {})
        semantic_status = f"skipped_error:{type(exc).__name__}"
        warnings = list(originality.get("warnings") or [])
        warnings.append(f"Semantic embeddings skipped: {type(exc).__name__}: {exc}")
        originality["warnings"] = warnings[:20]

    raw_compliance = dict(base.compliance_report or {})
    ai_style = raw_compliance.pop("ai_style", None)
    if not isinstance(ai_style, dict):
        ai_style = ai_style_report(body)

    return _apply_gate_fields(
        base,
        claims=list(base.claims or []),
        compliance=raw_compliance,
        originality=originality,
        ai_style=ai_style,
        semantic_embeddings=semantic_status,
    )


def gate_block_details(package: DeliveryPackage) -> dict[str, Any]:
    """供 PublishBlockedError.details 使用；含 server_reverify 摘要与 findings 前几条。"""
    compliance = package.compliance_report or {}
    originality = package.originality_report or {}
    quality = package.quality_report or {}
    server = quality.get("server_reverify") or {}
    findings = compliance.get("findings") or []
    findings_preview = findings[:5] if isinstance(findings, list) else findings

    return {
        "publication_status": package.publication_status,
        "compliance_passed": bool(compliance.get("passed")),
        "compliance_findings": findings_preview,
        "originality_allowed": bool(originality.get("publication_allowed")),
        "semantic_similarity": originality.get("semantic_similarity"),
        "semantic_provider": originality.get("semantic_provider"),
        "unverified_claim_ids": [
            claim.id for claim in (package.claims or []) if not claim.verified
        ],
        "server_reverified": bool(quality.get("server_reverified")),
        "server_reverify": {
            "semantic_embeddings": server.get("semantic_embeddings"),
            "blocked": server.get("blocked"),
            "unverified_claim_count": server.get("unverified_claim_count"),
            "at": server.get("at"),
        },
    }