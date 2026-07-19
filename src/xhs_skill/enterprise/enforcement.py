from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from xhs_skill.core.auth import Principal
from xhs_skill.core.config import get_settings
from xhs_skill.enterprise.policy import get_policy_engine


def enforce_enterprise_policy(
    principal: Principal,
    operation: str,
    *,
    context: dict[str, Any] | None = None,
) -> None:
    settings = get_settings()
    # personal 配置档：企业平面关闭（见 Settings.profile）；enterprise 配置档会在 validator 中打开闸门
    if settings.profile == "personal":
        return
    if not settings.enterprise_enabled or not settings.enterprise_policy_enforcement:
        return
    decision = get_policy_engine().evaluate(principal, operation, context=context)
    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail={"reason": decision.reason, "obligations": decision.obligations},
        )
