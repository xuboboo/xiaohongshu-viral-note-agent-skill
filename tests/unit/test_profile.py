"""core/profile.py 单测：部署配置档功能门控。"""
import pytest

from xhs_skill.core import config as config_mod
from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.profile import (
    active_planes,
    current_profile,
    is_enabled,
    require,
)


@pytest.fixture(autouse=True)
def _setup_settings():
    """每个测试前重置 settings 缓存。"""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _apply_settings(monkeypatch, profile: str = "personal", **kwargs) -> Settings:
    """创建并注入测试 settings。"""
    settings = Settings(
        app_env="test",
        app_secret_key="Aa1!" + "x" * 36,
        deployment_profile=profile,
        model_providers_file="/dev/null",
        xhs_selector_config="/dev/null",
        xhs_accounts_config="/dev/null",
        xhs_session_dir="/tmp/test-sessions",
        xhs_screenshot_dir="/tmp/test-screenshots",
        object_storage_dir="/tmp/test-objects",
        enterprise_data_dir="/tmp/test-enterprise",
        **kwargs,
    )
    get_settings.cache_clear()
    monkeypatch.setattr(config_mod, "get_settings", lambda: settings)
    # profile 模块通过 from-import 绑定，需同步 monkeypatch
    import xhs_skill.core.profile as profile_mod

    monkeypatch.setattr(profile_mod, "get_settings", lambda: settings)
    return settings


class TestProfilePersonal:
    def test_personal_disables_enterprise_features(self, monkeypatch):
        _apply_settings(monkeypatch, "personal")

        assert current_profile() == "personal"
        assert is_enabled("research") is True
        assert is_enabled("generation") is True
        assert is_enabled("publishing") is True
        assert is_enabled("operations") is True
        assert is_enabled("enterprise_quota") is False
        assert is_enabled("enterprise_approvals") is False
        assert is_enabled("enterprise_scim") is False
        assert is_enabled("show_enterprise_cli") is False

    def test_personal_defaults_enterprise_gate_off(self, monkeypatch):
        settings = _apply_settings(monkeypatch, "personal")
        assert settings.enterprise_enabled is False
        assert settings.scim_enabled is False

    def test_personal_planes(self, monkeypatch):
        _apply_settings(monkeypatch, "personal")

        planes = active_planes()
        assert "content" in planes
        assert "publish" in planes
        assert "ops" in planes
        assert "enterprise" not in planes


class TestProfileTeam:
    def test_team_enables_audit_and_oidc(self, monkeypatch):
        _apply_settings(monkeypatch, "team")

        assert current_profile() == "team"
        assert is_enabled("enterprise_audit") is True
        assert is_enabled("enterprise_oidc") is True
        assert is_enabled("enterprise_quota") is False
        assert is_enabled("enterprise_scim") is False

    def test_team_planes(self, monkeypatch):
        _apply_settings(monkeypatch, "team")

        planes = active_planes()
        assert "content" in planes
        assert "enterprise" not in planes  # quota/approvals 未启用


class TestProfileEnterprise:
    def test_enterprise_profile_auto_enables_gate(self, monkeypatch):
        settings = _apply_settings(monkeypatch, "enterprise")
        assert settings.enterprise_enabled is True

    def test_enterprise_enables_all(self, monkeypatch):
        _apply_settings(monkeypatch, "enterprise", enterprise_enabled=True)

        assert current_profile() == "enterprise"
        assert is_enabled("enterprise_quota") is True
        assert is_enabled("enterprise_approvals") is True
        assert is_enabled("enterprise_audit") is True
        assert is_enabled("enterprise_oidc") is True
        assert is_enabled("enterprise_scim") is True
        assert is_enabled("show_enterprise_cli") is True

    def test_enterprise_planes(self, monkeypatch):
        _apply_settings(monkeypatch, "enterprise", enterprise_enabled=True)

        planes = active_planes()
        assert "enterprise" in planes


class TestRequire:
    def test_require_succeeds_for_enabled(self, monkeypatch):
        _apply_settings(monkeypatch, "enterprise", enterprise_enabled=True)

        require("enterprise_quota")  # 不应抛出

    def test_require_raises_for_disabled(self, monkeypatch):
        _apply_settings(monkeypatch, "personal")

        with pytest.raises(ValueError, match="not available"):
            require("enterprise_quota")


class TestIsEnabled:
    def test_unknown_feature_defaults_false(self, monkeypatch):
        _apply_settings(monkeypatch, "personal")

        assert is_enabled("nonexistent_feature") is False