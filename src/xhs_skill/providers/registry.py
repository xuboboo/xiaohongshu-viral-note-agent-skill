from __future__ import annotations

import builtins
import os
import re
from pathlib import Path

import yaml

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.providers.anthropic_messages import AnthropicMessagesProvider
from xhs_skill.providers.base import ModelProvider
from xhs_skill.providers.gemini import GeminiProvider
from xhs_skill.providers.openai_compatible import OpenAICompatibleProvider
from xhs_skill.providers.openai_responses import OpenAIResponsesProvider
from xhs_skill.schemas.provider import ModelCapabilities

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand(value):
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda match: os.getenv(match.group(1), ""), value)
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand(item) for item in value]
    return value


class ProviderRegistry:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._providers: dict[str, ModelProvider] = {}
        self._load_from_settings()
        self._load_from_file(self.settings.model_providers_file)

    def _add_openai_compatible(
        self,
        name: str,
        api_key: str | None,
        base_url: str | None,
        model: str | None,
        *,
        auth_header: str = "Authorization",
        auth_scheme: str = "Bearer",
        query_params: dict[str, str] | None = None,
        capabilities: dict | None = None,
    ) -> None:
        if api_key and base_url:
            self._providers[name] = OpenAICompatibleProvider(
                name=name,
                api_key=api_key,
                base_url=base_url,
                default_model=model,
                auth_header=auth_header,
                auth_scheme=auth_scheme,
                query_params=query_params,
                capabilities=ModelCapabilities.model_validate(capabilities) if capabilities else None,
            )

    def _load_from_settings(self) -> None:
        s = self.settings
        if s.openai_api_key:
            self._providers["openai"] = OpenAIResponsesProvider(
                s.openai_api_key, s.openai_base_url, s.openai_default_model
            )
        if s.anthropic_api_key:
            self._providers["anthropic"] = AnthropicMessagesProvider(
                s.anthropic_api_key, s.anthropic_base_url, s.anthropic_default_model
            )
        if s.gemini_api_key:
            self._providers["gemini"] = GeminiProvider(
                s.gemini_api_key, s.gemini_base_url, s.gemini_default_model
            )

        configs = [
            ("deepseek", s.deepseek_api_key, s.deepseek_base_url, s.deepseek_default_model),
            ("qwen", s.dashscope_api_key, s.dashscope_base_url, s.qwen_default_model),
            ("ark", s.ark_api_key, s.ark_base_url, s.ark_default_model),
            ("glm", s.zhipu_api_key, s.zhipu_base_url, s.glm_default_model),
            ("kimi", s.moonshot_api_key, s.moonshot_base_url, s.kimi_default_model),
            ("minimax", s.minimax_api_key, s.minimax_base_url, s.minimax_default_model),
            ("hunyuan", s.hunyuan_api_key, s.hunyuan_base_url, s.hunyuan_default_model),
            ("qianfan", s.qianfan_api_key, s.qianfan_base_url, s.qianfan_default_model),
        ]
        for config in configs:
            self._add_openai_compatible(*config)

    def _load_from_file(self, path: Path) -> None:
        if not path.exists():
            return
        data = _expand(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        for name, config in data.get("providers", {}).items():
            type_ = config.get("type", "openai_compatible")
            if type_ == "openai_compatible":
                self._add_openai_compatible(
                    name,
                    config.get("api_key"),
                    config.get("base_url"),
                    config.get("default_model"),
                    auth_header=config.get("auth_header", "Authorization"),
                    auth_scheme=config.get("auth_scheme", "Bearer"),
                    query_params=config.get("query_params"),
                    capabilities=config.get("capabilities"),
                )
            elif type_ in {"anthropic", "anthropic_compatible"} and config.get("api_key") and config.get("base_url"):
                self._providers[name] = AnthropicMessagesProvider(
                    config["api_key"],
                    config["base_url"],
                    config.get("default_model"),
                    name=name,
                    anthropic_version=config.get("anthropic_version", "2023-06-01"),
                )
            elif type_ == "gemini" and config.get("api_key") and config.get("base_url"):
                self._providers[name] = GeminiProvider(
                    config["api_key"], config["base_url"], config.get("default_model")
                )
            elif type_ == "bedrock" and config.get("region"):
                try:
                    from xhs_skill.providers.bedrock_converse import BedrockConverseProvider

                    self._providers[name] = BedrockConverseProvider(
                        config["region"], config.get("default_model")
                    )
                except ImportError:
                    # Optional provider dependencies should not prevent the runtime from starting.
                    continue

    def register(self, provider: ModelProvider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str) -> ModelProvider:
        if name not in self._providers:
            raise KeyError(f"Provider {name!r} is not configured")
        return self._providers[name]

    def list(self) -> list[str]:
        return sorted(self._providers)

    def candidates(self, preferred: str | None = None) -> builtins.list[ModelProvider]:
        ordered: list[ModelProvider] = []
        if preferred and preferred in self._providers:
            ordered.append(self._providers[preferred])
        for name in (
            "openai", "anthropic", "gemini", "deepseek", "qwen", "ark",
            "glm", "kimi", "minimax", "hunyuan", "qianfan"
        ):
            provider = self._providers.get(name)
            if provider and provider not in ordered:
                ordered.append(provider)
        for provider in self._providers.values():
            if provider not in ordered:
                ordered.append(provider)
        return ordered

    def choose(self, preferred: str | None = None) -> ModelProvider | None:
        if preferred:
            return self._providers.get(preferred)
        for name in ("openai", "anthropic", "gemini", "deepseek", "qwen", "ark", "glm"):
            if name in self._providers:
                return self._providers[name]
        return next(iter(self._providers.values()), None)
