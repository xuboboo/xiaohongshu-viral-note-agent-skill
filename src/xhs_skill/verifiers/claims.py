from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from uuid import uuid4

from xhs_skill.schemas.content import Claim, EvidenceReference

CLAIM_PATTERNS = [
    ("ABSOLUTE", re.compile(r"(?:第一|最好|唯一|100%|绝对安全)")),
    ("NUMBER", re.compile(r"\d+(?:%|万|元|天|个月|小时)")),
    ("EFFECT", re.compile(r"(?:改善|提升|降低|有效|功效)")),
    # 明显客观/营销断言：宁多进 ledger，要求 evidence 或删除，不可静默放过
    ("RANKING", re.compile(r"(?:销量第[一二三]|全网销量|行业第一|榜单第[一二三]|官方认证)")),
    ("SOCIAL_PROOF", re.compile(r"(?:用户都说|万人好评|零差评|爆卖|断货)")),
    ("OFFICIAL", re.compile(r"(?:官方独家|专利配方|临床验证|国家认证)")),
    # 强医疗/效果保证（窄匹配，避免误杀普通种草）
    ("GUARANTEE", re.compile(r"(?:药到病除|无效退款|包治百病|根治)")),
    ("MEDICAL_PROOF", re.compile(r"(?:临床证明|科学研究证明|医嘱推荐)")),
]

CLAIM_UNIT_SPLIT = re.compile(r"[。！？!?；;\n]+|(?<=[，,、])")


def _claim_units(text: str) -> list[str]:
    """Split compound copy so evidence for one fact cannot verify unrelated facts in the sentence."""
    units: list[str] = []
    for unit in CLAIM_UNIT_SPLIT.split(text):
        cleaned = unit.strip(" \t，,、；;。！？!?")
        if cleaned:
            units.append(cleaned)
    return units


def _normalize(value: str) -> str:
    return re.sub(r"[\s，。！？、；：,.!?;:()（）\[\]【】\"'“”‘’]", "", value).casefold()


def _evidence_expired(item: dict) -> bool:
    valid_until = item.get("valid_until")
    if not valid_until:
        return False
    try:
        parsed = datetime.fromisoformat(str(valid_until).replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed <= datetime.now(UTC)


def _matching_evidence(claim_text: str, evidence: list[dict]) -> list[EvidenceReference]:
    normalized_claim = _normalize(claim_text)
    matches: list[EvidenceReference] = []
    for item in evidence:
        source = str(item.get("source", "")).strip()
        excerpt = str(item.get("excerpt", "")).strip()
        bound_text = str(item.get("claim_text") or item.get("text") or "").strip()
        evidence_id = str(item.get("evidence_id") or item.get("id") or "").strip()
        if not source or not excerpt or not bound_text or not evidence_id or _evidence_expired(item):
            continue
        normalized_bound = _normalize(bound_text)
        if not normalized_bound:
            continue
        # Evidence must bind the normalized claim unit exactly. Substring matching is unsafe for
        # compound sentences because evidence for a price can otherwise validate an efficacy claim.
        exact_or_contained = normalized_bound == normalized_claim
        excerpt_normalized = _normalize(excerpt)
        excerpt_supports = normalized_bound in excerpt_normalized or normalized_claim in excerpt_normalized
        confidence = str(item.get("confidence", "MEDIUM")).upper()
        if exact_or_contained and excerpt_supports and confidence in {"MEDIUM", "HIGH"}:
            matches.append(
                EvidenceReference(
                    evidence_id=evidence_id,
                    source=source,
                    excerpt=excerpt,
                    locator=str(item.get("locator") or "") or None,
                    excerpt_sha256=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                    confidence=confidence,
                    valid_until=str(item.get("valid_until") or "") or None,
                )
            )
    return matches


def extract_claims(text: str, evidence: list[dict]) -> list[Claim]:
    seen: set[str] = set()
    claims: list[Claim] = []
    for cleaned in _claim_units(text):
        matching_types = [claim_type for claim_type, pattern in CLAIM_PATTERNS if pattern.search(cleaned)]
        if not matching_types or cleaned in seen:
            continue
        seen.add(cleaned)
        matched = _matching_evidence(cleaned, evidence)
        sources = sorted({item.source for item in matched})
        verified = bool(matched)
        confidence = (
            "HIGH"
            if any(item.confidence == "HIGH" for item in matched)
            else ("MEDIUM" if verified else "LOW")
        )
        claims.append(
            Claim(
                id=str(uuid4()),
                text=cleaned,
                claim_type="+".join(matching_types),
                sources=sources,
                evidence_refs=matched,
                verified=verified,
                confidence=confidence,
                publication_status="ALLOWED" if verified else "BLOCKED",
            )
        )
    return claims
