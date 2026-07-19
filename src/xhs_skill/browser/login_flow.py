from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import yaml

from xhs_skill.browser.manager import BrowserManager, ManagedBrowserSession
from xhs_skill.core.concurrency import get_concurrency_controller
from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.distributed_lock import get_distributed_lock_manager
from xhs_skill.core.identifiers import validate_identifier
from xhs_skill.schemas.publishing import AuthSession, LoginStatus


class LoginFlow:
    def __init__(
        self, settings: Settings | None = None, manager: BrowserManager | None = None
    ) -> None:
        self.settings = settings or get_settings()
        self.manager = manager or BrowserManager(self.settings)
        self._active: dict[str, ManagedBrowserSession] = {}
        self._status: dict[str, AuthSession] = {}
        self.concurrency = get_concurrency_controller()
        self.locks = get_distributed_lock_manager()

    @staticmethod
    def _key(tenant_id: str, account_id: str) -> str:
        tenant = validate_identifier(tenant_id, field="tenant_id")
        account = validate_identifier(account_id, field="account_id")
        return hashlib.sha256(f"{tenant}\0{account}".encode()).hexdigest()

    async def start(self, account_id: str, tenant_id: str = "local") -> AuthSession:
        key = self._key(tenant_id, account_id)
        async with self.locks.lock(f"account-browser:{key}"):
            async with self.concurrency.operation_slot("browser"):
                existing = self._active.get(key)
                if existing:
                    await existing.close()
                session = await self.manager.open(key, restore=True)
                self._active[key] = session
                await session.page.goto(
                    self.settings.xhs_creator_studio_url, wait_until="domcontentloaded"
                )
                await asyncio.sleep(2)
                screenshot = self.settings.xhs_screenshot_dir / f"login-{key}-{uuid4()}.png"
                await session.page.screenshot(path=str(screenshot), full_page=True)
                try:
                    screenshot.chmod(0o600)
                except OSError:
                    pass
                status = await self._detect_status(account_id, tenant_id, key, session, screenshot)
                self._status[key] = status
                return status

    def _account_policy(self, account_id: str, tenant_id: str) -> dict:
        path = self.settings.xhs_accounts_config
        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        tenant_policy = (
            data.get("tenants", {}).get(tenant_id, {}).get("accounts", {}).get(account_id, {})
        )
        global_policy = data.get("accounts", {}).get(account_id, {})
        return dict(tenant_policy or global_policy or {})

    async def _display_name(self, session: ManagedBrowserSession) -> str | None:
        try:
            selectors = (
                yaml.safe_load(self.settings.xhs_selector_config.read_text(encoding="utf-8")) or {}
            )
            for selector in selectors.get("login", {}).get("account_name_css", []):
                locator = session.page.locator(selector)
                if await locator.count() and await locator.first.is_visible():
                    value = (await locator.first.inner_text()).strip()
                    if value:
                        return re.sub(r"\s+", " ", value)[:200]
        except Exception:
            return None
        return None

    async def _detect_status(
        self,
        account_id: str,
        tenant_id: str,
        key: str,
        session: ManagedBrowserSession,
        screenshot: Path | None = None,
    ) -> AuthSession:
        url = session.page.url
        text = (await session.page.locator("body").inner_text())[:10000]
        if any(term in text for term in ("验证码", "安全验证", "风险验证")):
            status = LoginStatus.RISK_VERIFICATION_REQUIRED
        elif "login" not in url.lower() and any(
            term in text for term in ("创作中心", "发布笔记", "数据看板", "专业号")
        ):
            status = LoginStatus.AUTHENTICATED
        elif any(term in text for term in ("扫码登录", "二维码", "登录")):
            status = LoginStatus.QR_CODE_READY
        else:
            status = LoginStatus.WAITING_FOR_SCAN
        display_name = await self._display_name(session)
        policy = self._account_policy(account_id, tenant_id)
        expected_name = str(policy.get("expected_display_name", "")).strip()
        expected_url = str(policy.get("expected_profile_url_contains", "")).strip()
        strict = bool(policy.get("strict_identity_match", False))
        warnings: list[str] = []
        identity_verified = False
        if status == LoginStatus.AUTHENTICATED:
            name_ok = not expected_name or (
                display_name and expected_name.casefold() in display_name.casefold()
            )
            url_ok = not expected_url or expected_url in url
            identity_verified = bool((expected_name or expected_url) and name_ok and url_ok)
            if strict and not identity_verified:
                status = LoginStatus.ACCOUNT_MISMATCH
                self.manager.store.delete(key)
                warnings.append("登录账号与配置的目标账号身份不匹配，未保存会话。")
            else:
                if not (expected_name or expected_url):
                    warnings.append("未配置目标账号身份；会话已认证，但发布前仍需人工核对账号。")
                elif not identity_verified:
                    warnings.append(
                        "账号身份与配置未完全匹配；当前为非严格模式，发布前必须人工确认。"
                    )
                await self.manager.save(key, session)

        previous = self._status.get(key)
        authenticated_at = (
            previous.authenticated_at
            if previous and previous.authenticated_at and status == LoginStatus.AUTHENTICATED
            else (datetime.now(UTC) if status == LoginStatus.AUTHENTICATED else None)
        )
        expires_at = (
            previous.expires_at
            if previous and previous.expires_at and status == LoginStatus.AUTHENTICATED
            else (
                datetime.now(UTC) + timedelta(days=7)
                if status == LoginStatus.AUTHENTICATED
                else None
            )
        )
        return AuthSession(
            id=previous.id if previous else str(uuid4()),
            account_id=account_id,
            tenant_id=tenant_id,
            status=status,
            qr_image_path=str(screenshot)
            if screenshot
            else (previous.qr_image_path if previous else None),
            qr_image_url=f"/v1/accounts/{account_id}/auth/qr"
            if screenshot or (previous and previous.qr_image_path)
            else None,
            authenticated_at=authenticated_at,
            expires_at=expires_at,
            last_verified_at=datetime.now(UTC),
            account_display_name=display_name,
            identity_verified=identity_verified,
            warnings=warnings,
        )

    async def status(self, account_id: str, tenant_id: str = "local") -> AuthSession:
        key = self._key(tenant_id, account_id)
        async with self.locks.lock(f"account-browser:{key}"):
            async with self.concurrency.operation_slot("browser"):
                session = self._active.get(key)
                if session:
                    status = await self._detect_status(account_id, tenant_id, key, session)
                    self._status[key] = status
                    return status
                stored = self.manager.store.load(key)
                if stored:
                    session = await self.manager.open(key, restore=True)
                    try:
                        await session.page.goto(
                            self.settings.xhs_creator_studio_url, wait_until="domcontentloaded"
                        )
                        status = await self._detect_status(account_id, tenant_id, key, session)
                        if status.status == LoginStatus.AUTHENTICATED:
                            self._active[key] = session
                            return status
                    finally:
                        if key not in self._active:
                            await session.close()
                return AuthSession(
                    id=str(uuid4()),
                    account_id=account_id,
                    tenant_id=tenant_id,
                    status=LoginStatus.LOGIN_REQUIRED,
                )

    async def logout(
        self, account_id: str, *, tenant_id: str = "local", delete_session: bool = True
    ) -> AuthSession:
        key = self._key(tenant_id, account_id)
        async with self.locks.lock(f"account-browser:{key}"):
            async with self.concurrency.operation_slot("browser"):
                session = self._active.pop(key, None)
                if session:
                    await session.close()
                if delete_session:
                    self.manager.store.delete(key)
                status = AuthSession(
                    id=str(uuid4()),
                    account_id=account_id,
                    tenant_id=tenant_id,
                    status=LoginStatus.LOGGED_OUT,
                )
                self._status[key] = status
                return status

    def get_active(self, account_id: str, tenant_id: str = "local") -> ManagedBrowserSession | None:
        return self._active.get(self._key(tenant_id, account_id))

    async def shutdown(self) -> None:
        sessions = list(self._active.values())
        self._active.clear()
        await asyncio.gather(*(session.close() for session in sessions), return_exceptions=True)
