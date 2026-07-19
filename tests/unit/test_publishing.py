import pytest

from xhs_skill.publishing.approvals import create_approval, validate_approval
from xhs_skill.schemas.content import DeliveryPackage
from xhs_skill.schemas.publishing import PublishDraft


def package():
    """无敏感 claim / 合规词的干净包（不依赖客户端假报告）。"""
    return DeliveryPackage(
        task_id="t",
        trace_id="tr",
        selected_title="通勤包怎么选更省心",
        body="先看容量和背负舒适度，再对照自己的使用场景，不适合的人群也可以直接跳过。",
        content_hash="hash",
    )


def test_approval_is_bound_to_hash(monkeypatch):
    draft = PublishDraft(id="d", account_id="a", package=package(), content_hash="hash")
    approval = create_approval(draft)
    token = approval.approval_token
    assert token is not None
    validate_approval(draft, approval, token)
    draft.content_hash = "changed"
    with pytest.raises(ValueError):
        validate_approval(draft, approval, token)


def test_scheduled_approval_cannot_be_reused_for_direct_publish() -> None:
    draft = PublishDraft(
        id="scheduled-draft", account_id="account", package=package(), content_hash="hash"
    )
    approval = create_approval(draft)
    token = approval.approval_token
    assert token is not None
    approval.scheduled_for = "schedule-1"
    with pytest.raises(ValueError, match="scheduled publication"):
        validate_approval(draft, approval, token)


@pytest.mark.asyncio
async def test_browser_publish_requires_explicit_disclosure_and_account_confirmations(
    tmp_path, monkeypatch
):
    from xhs_skill.browser import LoginFlow
    from xhs_skill.core.config import Settings
    from xhs_skill.core.errors import PublishBlockedError
    from xhs_skill.publishing import PublishingService
    from xhs_skill.publishing.repository import PublishingRepository

    settings = Settings(
        app_env="test",
        app_secret_key="Aa1!" + "x" * 48,
        xhs_session_dir=tmp_path / "sessions",
        xhs_screenshot_dir=tmp_path / "screenshots",
        object_storage_dir=tmp_path / "objects",
        xhs_publish_adapter="creator_studio",
        xhs_manual_export_dir=tmp_path / "exports",
    )
    service = PublishingService(
        login_flow=LoginFlow(settings),
        repository=PublishingRepository(tmp_path / "publishing"),
        settings=settings,
    )
    item = package()
    item.ai_labeling = {"explicit_label_required": "REVIEW"}
    item.strategy = {"commercial_status": "COMMERCIAL_COLLABORATION"}
    draft = service.create_draft("account", item)
    approval = service.approve(draft.id)
    token = approval.approval_token
    assert token is not None
    with pytest.raises(PublishBlockedError, match="AI disclosure"):
        await service.publish(draft.id, token)


@pytest.mark.asyncio
async def test_verified_publish_enqueues_post_publish_sync(tmp_path):
    from pathlib import Path

    from xhs_skill.browser import LoginFlow
    from xhs_skill.core.config import Settings
    from xhs_skill.publishing import PublishingService
    from xhs_skill.publishing.repository import PublishingRepository

    class VerifiedPublisher:
        async def prepare(self, draft):
            target = tmp_path / "preview.json"
            target.write_text("{}")
            return target

        async def save_draft(self, draft):
            return {"saved": True}

        async def submit(self, draft):
            return {
                "verified": True,
                "url": "https://www.xiaohongshu.com/explore/test-note",
                "note_id": "test-note",
                "page_text": "发布成功",
                "submission_detected": True,
            }

    settings = Settings(
        app_env="test",
        app_secret_key="Aa1!" + "x" * 48,
        data_dir=tmp_path / "data",
        operations_db_path=tmp_path / "operations.sqlite3",
        xhs_session_dir=tmp_path / "sessions",
        xhs_screenshot_dir=tmp_path / "screenshots",
        xhs_manual_export_dir=tmp_path / "exports",
        object_storage_dir=tmp_path / "objects",
        xhs_publish_adapter="manual_export",
        post_publish_sync_enabled=True,
        post_publish_sync_delays_minutes=[60, 1440, 4320],
    )
    service = PublishingService(
        login_flow=LoginFlow(settings),
        repository=PublishingRepository(tmp_path / "publishing"),
        settings=settings,
    )
    service.publisher = VerifiedPublisher()
    item = package()
    item.strategy = {"commercial_status": "NON_COMMERCIAL"}
    draft = service.create_draft("account", item, tenant_id="tenant")
    approval = service.approve(draft.id, tenant_id="tenant")
    token = approval.approval_token
    assert token is not None
    result = await service.publish(draft.id, token, tenant_id="tenant")
    assert result.status == "VERIFIED"
    task_ids = result.audit["post_publish_sync_task_ids"]
    assert len(task_ids) == 3
    assert Path(settings.operations_db_path).is_file()