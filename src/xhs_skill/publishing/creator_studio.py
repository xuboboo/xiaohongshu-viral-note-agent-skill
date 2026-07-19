from __future__ import annotations

import asyncio
import re
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import yaml
from playwright.async_api import Locator, Page

from xhs_skill.browser.login_flow import LoginFlow
from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.errors import AuthenticationRequiredError, UnsupportedUIVersionError
from xhs_skill.schemas.publishing import LoginStatus, PublishDraft
from xhs_skill.storage.assets import AssetStore


class CreatorStudioPublisher:
    """Authorized browser publisher that fails closed on unknown UI or account risk checks."""

    def __init__(
        self,
        login_flow: LoginFlow,
        settings: Settings | None = None,
        asset_store: AssetStore | None = None,
    ) -> None:
        self.login_flow = login_flow
        self.settings = settings or get_settings()
        self.asset_store = asset_store or AssetStore(self.settings)
        self.selectors = (
            yaml.safe_load(self.settings.xhs_selector_config.read_text(encoding="utf-8")) or {}
        )

    async def _page_for_draft(self, draft: PublishDraft) -> Page:
        session = self.login_flow.get_active(draft.account_id, draft.tenant_id)
        if not session:
            status = await self.login_flow.status(draft.account_id, draft.tenant_id)
            session = self.login_flow.get_active(draft.account_id, draft.tenant_id)
            if status.status != LoginStatus.AUTHENTICATED or not session:
                raise AuthenticationRequiredError("Authorized creator session is required")
        return session.page

    async def _verify_account_identity(self, draft: PublishDraft) -> None:
        status = await self.login_flow.status(draft.account_id, draft.tenant_id)
        if status.status != LoginStatus.AUTHENTICATED:
            raise AuthenticationRequiredError("Authorized creator session is not authenticated")
        if self.settings.xhs_require_identity_verified and not status.identity_verified:
            raise AuthenticationRequiredError(
                "Target account identity is not system-verified; configure a strict account identity policy"
            )

    async def _first_visible(self, page: Page, texts: list[str]) -> Locator | None:
        for text in texts:
            locator = page.get_by_text(text, exact=False)
            if await locator.count() and await locator.first.is_visible():
                return locator.first
        return None

    async def _find_field(
        self,
        page: Page,
        *,
        placeholders: list[str],
        labels: list[str],
        css: list[str],
    ) -> Locator | None:
        for placeholder in placeholders:
            locator = page.get_by_placeholder(placeholder, exact=False)
            if await locator.count() and await locator.first.is_visible():
                return locator.first
        for label in labels:
            locator = page.get_by_label(label, exact=False)
            if await locator.count() and await locator.first.is_visible():
                return locator.first
        for selector in css:
            locator = page.locator(selector)
            if await locator.count() and await locator.first.is_visible():
                return locator.first
        return None

    async def _assert_safe_page(self, page: Page) -> str:
        body = (await page.locator("body").inner_text())[:20000]
        if any(term in body for term in ("验证码", "安全验证", "风险验证", "账号异常")):
            raise AuthenticationRequiredError("Risk verification requires user action")
        return body

    def _is_video(self, draft: PublishDraft) -> bool:
        if draft.package.video_script is not None:
            return True
        video_types = {"video/mp4", "video/quicktime", "video/webm"}
        for asset_id in draft.package.media_assets:
            try:
                if self.asset_store.metadata(draft.tenant_id, asset_id).content_type in video_types:
                    return True
            except (FileNotFoundError, KeyError, ValueError):
                continue
        return False

    async def check_selector_health(
        self,
        account_id: str,
        tenant_id: str = "local",
    ) -> dict:
        """检查发布页关键选择器是否可见，返回 ok/missing/ui_version_hint。"""
        session = self.login_flow.get_active(account_id, tenant_id)
        if not session:
            status = await self.login_flow.status(account_id, tenant_id)
            session = self.login_flow.get_active(account_id, tenant_id)
            if status.status != LoginStatus.AUTHENTICATED or not session:
                return {"ok": False, "error": "not_authenticated", "missing": [], "ui_version_hint": "unknown"}

        page = session.page
        await page.goto(self.settings.xhs_creator_studio_url, wait_until="domcontentloaded")
        await asyncio.sleep(1)

        config = self.selectors.get("publish", {})
        critical_keys = [
            "entry_text",
            "title_placeholders",
            "body_placeholders",
            "topic_placeholders",
            "file_input_css",
            "submit_text",
        ]
        missing: list[str] = []
        found: list[str] = []

        for key in critical_keys:
            targets = config.get(key, [])
            if not targets:
                missing.append(key)
                continue
            locator = await self._first_visible(page, targets)
            if locator:
                found.append(key)
            else:
                # CSS fallback: try direct locator
                if targets and any(t.startswith(("[", ".", "#", "input")) for t in targets):
                    for t in targets:
                        loc = page.locator(t)
                        if await loc.count():
                            found.append(key)
                            break
                    else:
                        missing.append(key)
                else:
                    missing.append(key)

        body_text = (await page.locator("body").inner_text())[:3000]
        ui_hint = "standard"
        if "新版" in body_text or "全新" in body_text:
            ui_hint = "new_version"

        return {
            "ok": len(missing) == 0,
            "found": found,
            "missing": missing,
            "ui_version_hint": ui_hint,
        }

    async def _select_format(self, page: Page, draft: PublishDraft) -> None:
        config = self.selectors.get("publish", {})
        key = "video_tab_text" if self._is_video(draft) else "graphic_tab_text"
        tab = await self._first_visible(page, config.get(key, []))
        if tab:
            await tab.click()
            await asyncio.sleep(0.5)

    async def _upload_assets(self, page: Page, draft: PublishDraft) -> None:
        if not draft.package.media_assets:
            return
        config = self.selectors.get("publish", {})
        file_input = await self._find_field(
            page,
            placeholders=[],
            labels=[],
            css=config.get("file_input_css", []),
        )
        if not file_input:
            raise UnsupportedUIVersionError("Media upload input was not recognized")
        allowed = {
            "image/jpeg",
            "image/png",
            "image/webp",
            "image/gif",
            "video/mp4",
            "video/quicktime",
            "video/webm",
        }
        paths = [
            str(self.asset_store.resolve(draft.tenant_id, asset_id, allowed_types=allowed))
            for asset_id in draft.package.media_assets
        ]
        await file_input.set_input_files(paths)
        await asyncio.sleep(min(8, 1 + len(paths)))

    async def _upload_cover(self, page: Page, draft: PublishDraft) -> None:
        if not draft.package.cover_asset:
            return
        path = self.asset_store.resolve(
            draft.tenant_id,
            draft.package.cover_asset,
            allowed_types={"image/jpeg", "image/png", "image/webp"},
        )
        config = self.selectors.get("publish", {})
        cover = await self._find_field(
            page,
            placeholders=[],
            labels=[],
            css=config.get("cover_input_css", []),
        )
        if cover:
            await cover.set_input_files(str(path))
            await asyncio.sleep(1)

    async def _fill_optional_fields(self, page: Page, draft: PublishDraft) -> None:
        config = self.selectors.get("publish", {})
        topics = draft.package.topics or [item.lstrip("#") for item in draft.package.hashtags]
        # 规范化：去 #、去空、保序去重
        normalized_topics: list[str] = []
        seen: set[str] = set()
        for raw in topics:
            topic = str(raw).lstrip("#").strip()
            if not topic or topic in seen:
                continue
            seen.add(topic)
            normalized_topics.append(topic)
        topic_field = await self._find_field(
            page,
            placeholders=config.get("topic_placeholders", []),
            labels=config.get("topic_labels", []),
            css=config.get("topic_css", []),
        )
        if topic_field and normalized_topics:
            # 稳妥策略：话题框只写第一个；额外话题已由 prepare() 写入正文 #tag。
            # 若控件支持空格分隔多话题，可配置 multi_topic_fill=space（默认 off，避免 UI 循环点选）。
            multi_mode = str(config.get("multi_topic_fill") or "first_only").strip().lower()
            if multi_mode == "space" and len(normalized_topics) > 1:
                await topic_field.fill(" ".join(normalized_topics[:5]))
            else:
                await topic_field.fill(normalized_topics[0])
        if draft.package.location:
            location_field = await self._find_field(
                page,
                placeholders=config.get("location_placeholders", []),
                labels=config.get("location_labels", []),
                css=config.get("location_css", []),
            )
            if location_field:
                await location_field.fill(draft.package.location)

    async def prepare(self, draft: PublishDraft) -> Path:
        await self._verify_account_identity(draft)
        page = await self._page_for_draft(draft)
        await page.goto(self.settings.xhs_creator_studio_url, wait_until="domcontentloaded")
        await asyncio.sleep(1)
        await self._assert_safe_page(page)
        config = self.selectors.get("publish", {})
        entry = await self._first_visible(page, config.get("entry_text", []))
        if entry:
            await entry.click()
            await asyncio.sleep(1)
        else:
            body = (await page.locator("body").inner_text())[:5000]
            if not any(text in body for text in config.get("entry_text", [])):
                raise UnsupportedUIVersionError(
                    "Creator Studio publishing entry was not recognized"
                )

        await self._select_format(page, draft)
        await self._upload_assets(page, draft)

        title_locator = await self._find_field(
            page,
            placeholders=config.get("title_placeholders", []),
            labels=config.get("title_labels", []),
            css=config.get("title_css", []),
        )
        body_locator = await self._find_field(
            page,
            placeholders=config.get("body_placeholders", []),
            labels=config.get("body_labels", []),
            css=config.get("body_css", []),
        )
        if not title_locator or not body_locator:
            raise UnsupportedUIVersionError("Title/body fields were not recognized")
        await title_locator.fill(draft.package.selected_title)
        body_text = draft.package.body
        # 话题策略：UI 话题框只填第一个（_fill_optional_fields）；其余以 #tag 追加正文，避免多话题控件循环点选易碎。
        tags = draft.package.topics or draft.package.hashtags
        if tags:
            normalized = []
            seen: set[str] = set()
            for item in tags:
                tag = item if str(item).startswith("#") else f"#{str(item).lstrip('#')}"
                key = tag.lstrip("#")
                if not key or key in seen:
                    continue
                seen.add(key)
                normalized.append(tag)
            if normalized:
                # 避免重复追加已在正文中的标签
                missing = [tag for tag in normalized if tag not in body_text]
                if missing:
                    body_text += "\n\n" + " ".join(missing)
        await body_locator.fill(body_text)
        await self._fill_optional_fields(page, draft)
        await self._upload_cover(page, draft)
        await self._assert_safe_page(page)

        preview = self.settings.xhs_screenshot_dir / f"preview-{draft.id}-{uuid4()}.png"
        await page.screenshot(path=str(preview), full_page=True)
        try:
            preview.chmod(0o600)
        except OSError:
            pass
        return preview

    async def save_draft(self, draft: PublishDraft) -> dict:
        await self._verify_account_identity(draft)
        page = await self._page_for_draft(draft)
        button = await self._first_visible(
            page, self.selectors.get("publish", {}).get("draft_text", [])
        )
        if not button:
            raise UnsupportedUIVersionError("Save-draft button was not recognized")
        await button.click()
        await asyncio.sleep(2)
        await self._assert_safe_page(page)
        return {"saved": True, "url": page.url}

    async def submit(self, draft: PublishDraft) -> dict:
        await self._verify_account_identity(draft)
        page = await self._page_for_draft(draft)
        final_text = await self._assert_safe_page(page)
        submit = await self._first_visible(
            page, self.selectors.get("publish", {}).get("submit_text", [])
        )
        if not submit:
            raise UnsupportedUIVersionError("Publish button was not recognized")
        await submit.click()
        await asyncio.sleep(3)
        final_url = page.url
        final_text = (await page.locator("body").inner_text())[:5000]
        path_parts = [part for part in urlparse(final_url).path.split("/") if part]
        note_id: str | None = None
        if "explore" in path_parts:
            index = path_parts.index("explore")
            if index + 1 < len(path_parts):
                note_id = path_parts[index + 1]
        elif len(path_parts) >= 3 and path_parts[-3:-1] == ["discovery", "item"]:
            note_id = path_parts[-1]
        if note_id and not re.fullmatch(r"[A-Za-z0-9_-]{12,128}", note_id):
            note_id = None
        submission_detected = any(term in final_text for term in ("发布成功", "已发布", "发布完成"))
        verified = note_id is not None
        return {
            "url": final_url if verified else None,
            "note_id": note_id,
            "page_text": final_text,
            "submission_detected": submission_detected,
            "verified": verified,
        }
