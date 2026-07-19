from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from xhs_skill.intelligence.embeddings import HashingEmbeddingProvider
from xhs_skill.intelligence.text_similarity import (
    aggregate_similarity,
    minhash_jaccard,
    minhash_signature,
    rare_phrase_matches,
    simhash64,
    simhash_hamming,
)
from xhs_skill.research.trend_detector import detect_content_gaps, extract_topics
from xhs_skill.schemas.research import HotNoteCandidate
from xhs_skill.verifiers.originality import originality_report_async


def test_simhash_minhash_and_rare_phrase_detection() -> None:
    original = "敏感肌通勤防晒选择清单和补涂步骤"
    close = "敏感肌通勤防晒选择清单，以及补涂步骤"
    distant = "周末露营装备预算规划"
    assert simhash_hamming(simhash64(original), simhash64(close)) < simhash_hamming(
        simhash64(original), simhash64(distant)
    )
    assert minhash_jaccard(minhash_signature(original), minhash_signature(close)) > 0.4
    assert rare_phrase_matches(original, [close])
    report = aggregate_similarity(original, [close, distant])
    assert report["minhash_max_similarity"] > 0


@pytest.mark.asyncio
async def test_semantic_originality_blocks_close_paraphrase() -> None:
    result = await originality_report_async(
        "敏感肌通勤防晒怎么选，先看成分再看补涂便利性",
        ["敏感肌上班防晒选择方法：成分和补涂体验都要看"],
        embedder=HashingEmbeddingProvider(512),
    )
    assert result["semantic_similarity"] is not None
    assert result["semantic_provider"] == "hashing-ngram"


def test_trend_change_point_and_content_gap() -> None:
    now = datetime.now(UTC)
    notes: list[HotNoteCandidate] = []
    for day in range(8):
        count = 1 if day < 5 else 6
        for index in range(count):
            notes.append(
                HotNoteCandidate(
                    id=f"{day}-{index}",
                    url=f"https://example.com/{day}/{index}",
                    title="通勤防晒 敏感肌怎么选" if day >= 5 else "通勤护肤日常",
                    source_provider="engine-a" if index % 2 == 0 else "engine-b",
                    published_at=now - timedelta(days=7 - day),
                )
            )
    trends = extract_topics(notes, limit=20)
    assert any(item.change_point_detected for item in trends)
    gaps = detect_content_gaps(notes, trends)
    assert gaps
    assert all("gap_score" in item for item in gaps)


def test_claim_evidence_is_bound_to_the_specific_claim() -> None:
    from xhs_skill.verifiers.claims import extract_claims

    text = "这套方法7天提升50%，价格100元。"
    evidence = [
        {
            "evidence_id": "price-doc",
            "source": "authorized-product-sheet",
            "claim_text": "价格100元",
            "excerpt": "当前授权产品表显示价格100元。",
            "locator": "price.current",
            "confidence": "HIGH",
        }
    ]
    claims = extract_claims(text, evidence)
    assert any(claim.verified and "价格100元" in claim.text for claim in claims)
    unsupported = [claim for claim in claims if "7天提升50%" in claim.text]
    assert unsupported
    assert all(not claim.verified and not claim.evidence_refs for claim in unsupported)
    price_claim = next(claim for claim in claims if claim.verified)
    assert price_claim.evidence_refs[0].evidence_id == "price-doc"
    assert len(price_claim.evidence_refs[0].excerpt_sha256) == 64


@pytest.mark.asyncio
async def test_generation_passes_tenant_to_account_profile_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    from xhs_skill.generation.service import GenerationService
    from xhs_skill.schemas.content import GenerateRequest

    service = GenerationService()
    observed: dict[str, str] = {}

    async def profile_async(account_id: str, tenant_id: str):
        observed["account_id"] = account_id
        observed["tenant_id"] = tenant_id
        return None

    monkeypatch.setattr(service.accounts, "profile_async", profile_async)
    package = await service.generate(
        GenerateRequest(
            topic="通勤防晒",
            account_id="account-tenant-test",
            research_current_trends=False,
        ),
        tenant_id="tenant-isolated",
    )
    assert package.task_id
    assert observed == {
        "account_id": "account-tenant-test",
        "tenant_id": "tenant-isolated",
    }
