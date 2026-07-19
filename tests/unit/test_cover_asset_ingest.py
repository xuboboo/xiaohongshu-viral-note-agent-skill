"""封面图成功生成后入库为 cover_asset / media_assets。"""
from __future__ import annotations

from pathlib import Path

import pytest

from xhs_skill.core.config import Settings
from xhs_skill.generation.service import GenerationService
from xhs_skill.providers.base import ImageResult, NoOpImageProvider
from xhs_skill.schemas.content import GenerateRequest
from xhs_skill.storage.assets import AssetStore


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        app_secret_key="Aa1!" + "x" * 36,
        deployment_profile="personal",
        object_storage_dir=tmp_path / "objects",
        model_providers_file="/dev/null",
        xhs_selector_config="/dev/null",
        xhs_accounts_config="/dev/null",
        xhs_session_dir=tmp_path / "sessions",
        xhs_screenshot_dir=tmp_path / "screenshots",
        enterprise_data_dir=tmp_path / "enterprise",
    )


class _FakeImageProvider:
    name = "fake"

    def __init__(self, path: Path) -> None:
        self.path = path

    async def generate_cover(self, prompt: str, *, width: int = 1080, height: int = 1440) -> ImageResult:
        return ImageResult(path=self.path, width=width, height=height, media_type="image/png")


@pytest.mark.asyncio
async def test_cover_ingested_into_asset_store(tmp_path):
    png = tmp_path / "cover.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    settings = _settings(tmp_path)
    store = AssetStore(settings)
    service = GenerationService(
        image_provider=_FakeImageProvider(png),
        asset_store=store,
    )
    package = await service.generate(
        GenerateRequest(topic="空气炸锅", research_current_trends=False),
        tenant_id="tenant_test",
    )
    assert package.cover_asset
    assert package.cover_asset in package.media_assets
    assert package.quality_report.get("cover_image_pending_ingest") is False
    resolved = store.resolve("tenant_test", package.cover_asset, allowed_types={"image/png"})
    assert resolved.is_file()


@pytest.mark.asyncio
async def test_noop_image_provider_does_not_break_generate(tmp_path):
    settings = _settings(tmp_path)
    store = AssetStore(settings)
    service = GenerationService(image_provider=NoOpImageProvider(), asset_store=store)
    package = await service.generate(
        GenerateRequest(topic="空气炸锅", research_current_trends=False),
        tenant_id="tenant_test",
    )
    assert package.cover_asset is None
    assert package.media_assets == []
    assert package.body