from __future__ import annotations

from pathlib import Path
from typing import Protocol

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.errors import ConfigurationError
from xhs_skill.core.identifiers import atomic_write_private, private_mkdir
from xhs_skill.schemas.publishing import PublishDraft


class PublishingAdapter(Protocol):
    async def prepare(self, draft: PublishDraft) -> Path: ...
    async def submit(self, draft: PublishDraft) -> dict: ...
    async def save_draft(self, draft: PublishDraft) -> dict: ...


class ManualExportPublisher:
    """Fail-safe adapter that exports a complete publishing package without side effects."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _dir(self, draft: PublishDraft) -> Path:
        path = self.settings.xhs_manual_export_dir / draft.id
        return private_mkdir(path)

    async def prepare(self, draft: PublishDraft) -> Path:
        folder = self._dir(draft)
        package_path = folder / "delivery-package.json"
        atomic_write_private(package_path, draft.package.model_dump_json(indent=2).encode("utf-8"))
        instructions = folder / "PUBLISHING_INSTRUCTIONS.md"
        atomic_write_private(
            instructions,
            (
                "# 人工发布包\n\n"
                f"标题：{draft.package.selected_title}\n\n"
                f"正文：\n\n{draft.package.body}\n\n"
                f"话题：{' '.join(draft.package.topics or draft.package.hashtags)}\n\n"
                "请由账号所有者登录小红书创作中心，核对账号、素材、商业披露和 AI 标识后发布。\n"
            ).encode(),
        )
        return package_path

    async def save_draft(self, draft: PublishDraft) -> dict:
        path = await self.prepare(draft)
        return {"saved": True, "manual_export": str(path)}

    async def submit(self, draft: PublishDraft) -> dict:
        path = await self.prepare(draft)
        return {
            "verified": False,
            "manual_export": str(path),
            "page_text": "Manual export created; no platform-side publication occurred.",
            "url": None,
        }


class OfficialApiPublisher:
    """Reserved official-publish adapter.

    It intentionally fails closed until an official, authorized publishing endpoint is configured.
    """

    def __init__(self, endpoint: str | None = None) -> None:
        self.endpoint = endpoint

    async def prepare(self, draft: PublishDraft) -> Path:
        raise ConfigurationError("Official publishing API is not configured")

    async def save_draft(self, draft: PublishDraft) -> dict:
        raise ConfigurationError("Official publishing API is not configured")

    async def submit(self, draft: PublishDraft) -> dict:
        raise ConfigurationError("Official publishing API is not configured")
