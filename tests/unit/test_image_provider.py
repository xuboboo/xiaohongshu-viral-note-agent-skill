"""Image provider 工厂与 NoOp / auto / dashscope 行为。"""
from xhs_skill.core.config import Settings
from xhs_skill.providers.base import NoOpImageProvider
from xhs_skill.providers.openai_images import OpenAICompatibleImageProvider, get_image_provider


def _settings(**kwargs) -> Settings:
    base = dict(
        app_env="test",
        app_secret_key="Aa1!" + "x" * 36,
        deployment_profile="personal",
        model_providers_file="/dev/null",
        xhs_selector_config="/dev/null",
        xhs_accounts_config="/dev/null",
        xhs_session_dir="/tmp/test-sessions",
        xhs_screenshot_dir="/tmp/test-screenshots",
        object_storage_dir="/tmp/test-objects",
        enterprise_data_dir="/tmp/test-enterprise",
    )
    base.update(kwargs)
    return Settings(**base)


def test_explicit_noop():
    provider = get_image_provider(_settings(image_provider="noop"))
    assert isinstance(provider, NoOpImageProvider)


def test_openai_image_provider_when_key_present():
    provider = get_image_provider(
        _settings(
            image_provider="openai",
            image_api_key="sk-test",
            image_model="gpt-image-1",
        )
    )
    assert isinstance(provider, OpenAICompatibleImageProvider)
    assert provider.model == "gpt-image-1"
    assert provider.vendor == "openai"


def test_openai_without_key_falls_back_noop():
    provider = get_image_provider(
        _settings(image_provider="openai", image_api_key=None, openai_api_key=None)
    )
    assert isinstance(provider, NoOpImageProvider)


def test_auto_picks_openai_key():
    provider = get_image_provider(
        _settings(image_provider="auto", openai_api_key="sk-openai", image_api_key=None)
    )
    assert isinstance(provider, OpenAICompatibleImageProvider)
    assert provider.vendor == "openai"


def test_auto_picks_dashscope_key():
    provider = get_image_provider(
        _settings(
            image_provider="auto",
            openai_api_key=None,
            image_api_key=None,
            dashscope_api_key="sk-dash",
        )
    )
    assert isinstance(provider, OpenAICompatibleImageProvider)
    assert provider.vendor == "dashscope"
    assert "dashscope" in provider.base_url or "qwen" in provider.model


def test_explicit_dashscope():
    provider = get_image_provider(
        _settings(image_provider="dashscope", dashscope_api_key="sk-dash")
    )
    assert isinstance(provider, OpenAICompatibleImageProvider)
    assert provider.vendor == "dashscope"