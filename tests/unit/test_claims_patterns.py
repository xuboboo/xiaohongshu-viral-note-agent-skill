"""Claim ledger 抽取覆盖。"""

from __future__ import annotations

from xhs_skill.verifiers.claims import extract_claims


def test_extract_ranking_and_social_proof_claims_unverified_without_evidence():
    text = "这款产品全网销量第一，用户都说好用，还有官方认证。"
    claims = extract_claims(text, evidence=[])
    types = " ".join(c.claim_type for c in claims)
    assert claims
    assert any(not c.verified for c in claims)
    assert "RANKING" in types or "SOCIAL_PROOF" in types or "OFFICIAL" in types


def test_extract_number_effect_still_works():
    claims = extract_claims("用了30天皮肤明显改善。", evidence=[])
    assert claims
    assert all(not c.verified for c in claims)


def test_extract_guarantee_and_medical_proof_claims():
    text = "这款产品药到病除，临床证明有效。"
    claims = extract_claims(text, evidence=[])
    types = " ".join(c.claim_type for c in claims)
    assert claims
    assert any(not c.verified for c in claims)
    assert "GUARANTEE" in types or "MEDICAL_PROOF" in types or "EFFECT" in types


def test_clean_seed_copy_does_not_force_claims():
    """普通种草文案不应因新模式被误抽 claim。"""
    text = "先看容量和背负舒适度，再对照自己的使用场景，不适合的人群也可以直接跳过。"
    claims = extract_claims(text, evidence=[])
    assert claims == []