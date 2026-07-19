from __future__ import annotations

from pathlib import Path

import pytest

from xhs_skill.core.config import Settings
from xhs_skill.publishing.adapters import ManualExportPublisher
from xhs_skill.schemas.content import DeliveryPackage
from xhs_skill.schemas.publishing import PublishDraft


@pytest.mark.asyncio
async def test_manual_export_is_side_effect_free(tmp_path: Path):
    settings = Settings(
        app_secret_key="x" * 40,
        xhs_manual_export_dir=tmp_path,
        xhs_session_dir=tmp_path / "sessions",
        xhs_screenshot_dir=tmp_path / "screenshots",
        object_storage_dir=tmp_path / "objects",
    )
    publisher = ManualExportPublisher(settings)
    package = DeliveryPackage(
        task_id="task",
        trace_id="trace",
        selected_title="标题",
        body="正文",
        content_hash="hash",
        topics=["测试话题"],
    )
    draft = PublishDraft(id="draft", account_id="account", package=package, content_hash="hash")
    path = await publisher.prepare(draft)
    assert path.is_file()
    result = await publisher.submit(draft)
    assert result["verified"] is False
    assert result["url"] is None
