"""发布门禁服务端重验：客户端报告不可信。"""

from __future__ import annotations

import pytest

from xhs_skill.core.errors import PublishBlockedError
from xhs_skill.intelligence.embeddings import HashingEmbeddingProvider
from xhs_skill.publishing.publication_gate import (
    gate_block_details,
    reverify_package,
    reverify_package_async,
)
from xhs_skill.schemas.content import Claim, DeliveryPackage
from xhs_skill.schemas.research import HotNoteCandidate


def _clean_package(**overrides) -> DeliveryPackage:
    base = dict(
        task_id="t",
        trace_id="tr",
        selected_title="通勤包怎么选更省心",
        body="先看容量和背负舒适度，再对照自己的使用场景，不适合的人群也可以直接跳过。",
        content_hash="client-hash",
        compliance_report={"passed": True},
        originality_report={"publication_allowed": True},
        publication_status="ALLOWED",
    )
    base.update(overrides)
    return DeliveryPackage(**base)


def _service(tmp_path):
    from xhs_skill.browser import LoginFlow
    from xhs_skill.core.config import Settings
    from xhs_skill.publishing import PublishingService
    from xhs_skill.publishing.repository import PublishingRepository

    settings = Settings(
        app_env="test",
        app_secret_key="Aa1!" + "x" * 48,
        xhs_session_dir=tmp_path / "sessions",
        xhs_screenshot_dir=tmp_path / "screenshots",
        object_storage_dir=tmp_path / "objects",
        xhs_publish_adapter="manual_export",
        xhs_manual_export_dir=tmp_path / "exports",
        embedding_provider="hashing",
    )
    return PublishingService(
        login_flow=LoginFlow(settings),
        repository=PublishingRepository(tmp_path / "publishing"),
        settings=settings,
    )


def test_reverify_ignores_forged_compliance_report():
    package = _clean_package(
        selected_title="神药",
        body="本产品可以治疗失眠，100%有效，永久有效。",
        compliance_report={"passed": True},
        originality_report={"publication_allowed": True},
        publication_status="ALLOWED",
    )
    out = reverify_package(package)
    assert out.compliance_report.get("passed") is False
    assert out.publication_status == "BLOCKED"
    assert out.quality_report.get("server_reverified") is True
    assert out.quality_report["server_reverify"]["semantic_embeddings"] == "skipped_sync_gate"


def test_reverify_ignores_forged_originality_report():
    ref = "今天分享一个通勤包挑选思路，先看容量和背负，再对照场景。" * 3
    package = _clean_package(
        body=ref,
        hot_notes=[
            HotNoteCandidate(
                id="n1",
                title="参考",
                url="https://example.com/n1",
                snippet=ref,
                body=ref,
                source_provider="fixture",
            )
        ],
        originality_report={"publication_allowed": True},
        compliance_report={"passed": True},
    )
    out = reverify_package(package)
    assert out.originality_report.get("publication_allowed") is False
    assert out.publication_status == "BLOCKED"


def test_reverify_ignores_forged_verified_claims():
    package = _clean_package(
        body="用了30天皮肤明显改善，功效惊人。",
        claims=[
            Claim(
                id="fake",
                text="用了30天皮肤明显改善",
                claim_type="NUMBER+EFFECT",
                verified=True,
                confidence="HIGH",
                publication_status="ALLOWED",
            )
        ],
        compliance_report={"passed": True},
        originality_report={"publication_allowed": True},
    )
    out = reverify_package(package)
    assert any(not c.verified for c in out.claims)
    assert out.publication_status == "BLOCKED"
    assert out.quality_report.get("server_reverified") is True


def test_reverify_clean_package_allows_human_review():
    package = _clean_package()
    out = reverify_package(package)
    assert out.quality_report.get("server_reverified") is True
    assert out.compliance_report.get("passed") is True
    assert out.originality_report.get("publication_allowed") is True
    assert out.publication_status == "HUMAN_REVIEW_REQUIRED"
    assert not any(not c.verified for c in out.claims)


def test_gate_block_details_includes_server_reverify_and_findings_preview():
    package = reverify_package(
        _clean_package(
            body="本产品可以治疗失眠，绝对安全，永久有效。",
            compliance_report={"passed": True},
        )
    )
    details = gate_block_details(package)
    assert details["server_reverified"] is True
    assert "server_reverify" in details
    assert details["server_reverify"].get("semantic_embeddings") == "skipped_sync_gate"
    findings = details.get("compliance_findings") or []
    assert isinstance(findings, list)
    assert len(findings) <= 5


@pytest.mark.asyncio
async def test_reverify_async_no_refs_skips_embeddings_without_crash():
    out = await reverify_package_async(_clean_package())
    assert out.publication_status == "HUMAN_REVIEW_REQUIRED"
    assert out.quality_report["server_reverify"]["semantic_embeddings"] == "skipped_no_references"
    assert out.originality_report.get("semantic_similarity") is None


@pytest.mark.asyncio
async def test_reverify_async_hashing_embedder_writes_semantic_fields():
    body = "先看容量和背负舒适度，再对照自己的使用场景。"
    ref = "周末露营装备预算规划与帐篷选购清单。"
    package = _clean_package(
        body=body,
        hot_notes=[
            HotNoteCandidate(
                id="n1",
                title="参考",
                url="https://example.com/n1",
                snippet=ref,
                body=ref,
                source_provider="fixture",
            )
        ],
    )
    out = await reverify_package_async(
        package,
        embedder=HashingEmbeddingProvider(512),
    )
    assert out.quality_report["server_reverify"]["semantic_embeddings"] == "evaluated"
    assert out.originality_report.get("semantic_similarity") is not None
    assert out.originality_report.get("semantic_provider") == "hashing-ngram"


@pytest.mark.asyncio
async def test_reverify_async_blocks_on_high_semantic_similarity(monkeypatch):
    """伪造高语义相似时 publication_allowed=False 且 BLOCKED。"""
    from xhs_skill.core.config import Settings

    settings = Settings(
        app_env="test",
        app_secret_key="Aa1!" + "x" * 48,
        semantic_similarity_block=0.5,
        embedding_provider="hashing",
    )
    body = "敏感肌通勤防晒怎么选，先看成分再看补涂便利性"
    # 与 body 高度重合，hashing-ngram 会给出较高余弦
    ref = "敏感肌通勤防晒怎么选，先看成分再看补涂便利性"
    package = _clean_package(
        body=body,
        hot_notes=[
            HotNoteCandidate(
                id="n1",
                title="参考",
                url="https://example.com/n1",
                snippet=ref,
                body=ref,
                source_provider="fixture",
            )
        ],
        compliance_report={"passed": True},
        originality_report={"publication_allowed": True},
    )
    out = await reverify_package_async(
        package,
        settings=settings,
        embedder=HashingEmbeddingProvider(512),
    )
    assert out.originality_report.get("semantic_similarity") is not None
    assert out.originality_report.get("semantic_similarity") >= 0.5
    assert out.originality_report.get("publication_allowed") is False
    assert out.publication_status == "BLOCKED"
    assert out.quality_report["server_reverify"]["semantic_embeddings"] == "evaluated"


@pytest.mark.asyncio
async def test_reverify_async_embedder_error_does_not_crash():
    class BoomEmbedder:
        name = "boom"

        async def embed(self, texts):
            raise RuntimeError("embedding unavailable")

    package = _clean_package(
        body="先看容量和背负舒适度，再对照自己的使用场景。",
        hot_notes=[
            HotNoteCandidate(
                id="n1",
                title="参考",
                url="https://example.com/n1",
                snippet="另一篇完全不同的露营装备笔记。",
                body="另一篇完全不同的露营装备笔记。",
                source_provider="fixture",
            )
        ],
    )
    out = await reverify_package_async(package, embedder=BoomEmbedder())
    status = out.quality_report["server_reverify"]["semantic_embeddings"]
    assert status.startswith("skipped_error:")
    assert out.publication_status in {"BLOCKED", "HUMAN_REVIEW_REQUIRED"}


@pytest.mark.asyncio
async def test_create_draft_rejects_forged_compliance(tmp_path):
    service = _service(tmp_path)
    toxic = _clean_package(
        body="保证减重，药到病除，100%安全。",
        compliance_report={"passed": True},
        originality_report={"publication_allowed": True},
        publication_status="ALLOWED",
    )
    with pytest.raises(PublishBlockedError, match="server-side verification|compliance") as excinfo:
        service.create_draft("account", toxic)
    details = excinfo.value.details
    assert "server_reverify" in details
    assert details.get("server_reverified") is True


@pytest.mark.asyncio
async def test_create_draft_clean_sets_server_reverified(tmp_path):
    service = _service(tmp_path)
    draft = service.create_draft("account", _clean_package())
    assert draft.package.quality_report.get("server_reverified") is True
    assert draft.package.publication_status == "HUMAN_REVIEW_REQUIRED"
    assert (
        draft.package.quality_report["server_reverify"]["semantic_embeddings"]
        == "skipped_sync_gate"
    )


@pytest.mark.asyncio
async def test_preflight_uses_async_reverify_and_blocks_after_body_tamper(tmp_path):
    service = _service(tmp_path)
    draft = service.create_draft("account", _clean_package())
    approval = service.approve(
        draft.id,
        ai_disclosure_confirmed=True,
        account_identity_confirmed=True,
    )
    draft = service.repository.load_draft(draft.id)
    draft.package = draft.package.model_copy(
        update={
            "body": "本产品可以治疗失眠，绝对安全，永久有效。",
            "compliance_report": {"passed": True},
            "originality_report": {"publication_allowed": True},
            "publication_status": "ALLOWED",
            "claims": [],
        }
    )
    draft.content_hash = service._canonical_content_hash(draft.package)
    draft.package = draft.package.model_copy(update={"content_hash": draft.content_hash})
    service.repository.save_draft(draft)

    with pytest.raises(PublishBlockedError) as excinfo:
        await service._preflight(draft, approval)
    assert excinfo.value.details.get("server_reverified") is True
    # async 路径：无 hot_notes 时为 skipped_no_references
    assert (
        excinfo.value.details.get("server_reverify", {}).get("semantic_embeddings")
        == "skipped_no_references"
    )


@pytest.mark.asyncio
async def test_preflight_calls_reverify_package_async(tmp_path, monkeypatch):
    service = _service(tmp_path)
    draft = service.create_draft("account", _clean_package())
    approval = service.approve(
        draft.id,
        ai_disclosure_confirmed=True,
        account_identity_confirmed=True,
    )
    draft = service.repository.load_draft(draft.id)
    called: list[str] = []

    async def _spy(package, *,_settings=None, **kwargs):
        called.append("async")
        return await reverify_package_async(package, settings=service.settings)

    monkeypatch.setattr(
        "xhs_skill.publishing.service.reverify_package_async",
        _spy,
    )
    await service._preflight(draft, approval)
    assert called == ["async"]
    assert (
        draft.package.quality_report["server_reverify"]["semantic_embeddings"]
        == "skipped_no_references"
    )