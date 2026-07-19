from __future__ import annotations

import re

from xhs_skill.browser.login_flow import LoginFlow
from xhs_skill.core.errors import AuthenticationRequiredError
from xhs_skill.schemas.account import AccountAnalytics
from xhs_skill.schemas.publishing import LoginStatus

_LABELS = {
    "followers": ("粉丝", "粉丝数"),
    "views_30d": ("观看", "阅读", "曝光"),
    "likes_30d": ("点赞",),
    "saves_30d": ("收藏",),
    "comments_30d": ("评论",),
    "shares_30d": ("分享",),
    "profile_visits_30d": ("主页访问",),
    "follows_gained_30d": ("新增粉丝", "新增关注"),
}


def _number(text: str) -> int | None:
    match = re.search(r"([\d,.]+)\s*([万wWkK]?)", text)
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    suffix = match.group(2).lower()
    if suffix in {"万", "w"}:
        value *= 10000
    elif suffix == "k":
        value *= 1000
    return int(value)


class BrowserAnalyticsSync:
    """Best-effort parser for data visible in an authorized creator session.

    The service never fabricates missing values. UI changes can result in null fields.
    """

    def __init__(self, login_flow: LoginFlow) -> None:
        self.login_flow = login_flow

    async def sync(self, account_id: str, tenant_id: str = "local") -> AccountAnalytics:
        status = await self.login_flow.status(account_id, tenant_id)
        session = self.login_flow.get_active(account_id, tenant_id)
        if status.status != LoginStatus.AUTHENTICATED or not session:
            raise AuthenticationRequiredError("Authorized creator session is required")
        page = session.page
        await page.goto(
            "https://creator.xiaohongshu.com/creator/home", wait_until="domcontentloaded"
        )
        text = (await page.locator("body").inner_text())[:50000]
        values: dict[str, int | None] = {}
        for field, labels in _LABELS.items():
            found = None
            for label in labels:
                match = re.search(rf"{re.escape(label)}[^\d]{{0,20}}([\d,.]+\s*[万wWkK]?)", text)
                if match:
                    found = _number(match.group(1))
                    break
            values[field] = found
        return AccountAnalytics(account_id=account_id, **values)
