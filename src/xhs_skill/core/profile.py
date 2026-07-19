"""部署配置档（profile）功能门控。

四平面职责：
- Content: research + generation + rewrite + verifiers → 输出 DeliveryPackage
- Publish: login + draft/approve/execute → 只吃 package hash
- Ops: metrics sync + attribution + calendar + bandit → 只吃 note_id
- Enterprise: quota + approvals + OIDC + outbox → 可选横切

profile 控制哪些平面对用户可见，不改变模块内部逻辑。
"""
from __future__ import annotations

from xhs_skill.core.config import get_settings


def is_enabled(feature: str) -> bool:
    """检查指定功能是否在当前 profile 下启用。"""
    return get_settings().profile_features.get(feature, False)


def require(feature: str) -> None:
    """要求指定功能启用，否则抛出 ValueError。"""
    if not is_enabled(feature):
        raise ValueError(
            f"Feature '{feature}' is not available in "
            f"'{get_settings().deployment_profile}' deployment profile"
        )


def current_profile() -> str:
    """返回当前 profile 名称。"""
    return get_settings().profile


def active_planes() -> list[str]:
    """返回当前 profile 下活跃的平面列表。"""
    planes = ["content", "publish", "ops"]
    if is_enabled("enterprise_quota") or is_enabled("enterprise_approvals"):
        planes.append("enterprise")
    return planes


def clear_cache() -> None:
    """清除 settings 缓存（测试用）。"""
    get_settings.cache_clear()