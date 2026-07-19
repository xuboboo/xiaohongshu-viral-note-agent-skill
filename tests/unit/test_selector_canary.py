"""publishing selector canary + 版本钉扎。"""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from xhs_skill.publishing.selector_health import (
    enrich_selector_health,
    selector_bundle_fingerprint,
)
from xhs_skill.publishing.service import PublishingService


@pytest.mark.asyncio
async def test_selector_health_unsupported_adapter(tmp_path):
    service = PublishingService.__new__(PublishingService)
    service.settings = MagicMock()
    service.settings.xhs_publish_adapter = "manual_export"
    service.settings.xhs_selector_config = tmp_path / "missing.yaml"
    service.settings.selector_pin_version = None
    service.settings.selector_canary_alert_webhook = None
    service.publisher = object()

    result = await PublishingService.check_selector_health(service, "acc-1", "local")
    assert result["ok"] is False
    assert result["error"] == "selector_health_unsupported"
    assert "selector_pin" in result


@pytest.mark.asyncio
async def test_selector_health_delegates_and_pins(tmp_path):
    from xhs_skill.publishing.creator_studio import CreatorStudioPublisher

    sel = tmp_path / "selectors.yaml"
    sel.write_text("publish:\n  entry_text: [发布]\n", encoding="utf-8")
    fp = selector_bundle_fingerprint(sel)

    service = PublishingService.__new__(PublishingService)
    service.settings = MagicMock()
    service.settings.xhs_publish_adapter = "creator_studio"
    service.settings.xhs_selector_config = sel
    service.settings.selector_pin_version = fp["sha256"]
    service.settings.selector_canary_alert_webhook = None
    publisher = MagicMock(spec=CreatorStudioPublisher)
    publisher.check_selector_health = AsyncMock(
        return_value={
            "ok": True,
            "found": ["title_placeholders"],
            "missing": [],
            "ui_version_hint": "standard",
        }
    )
    service.publisher = publisher

    result = await PublishingService.check_selector_health(service, "acc-1", "t1")
    assert result["ok"] is True
    assert result["selector_pin"]["status"] == "match"
    publisher.check_selector_health.assert_awaited_once_with("acc-1", "t1")


def test_pin_mismatch_marks_not_ok(tmp_path):
    sel = tmp_path / "selectors.yaml"
    sel.write_text("publish: {}\n", encoding="utf-8")
    settings = MagicMock()
    settings.xhs_selector_config = sel
    settings.selector_pin_version = "deadbeef" * 8
    enriched = enrich_selector_health({"ok": True, "missing": []}, settings)
    assert enriched["ok"] is False
    assert enriched["selector_pin"]["status"] == "mismatch"