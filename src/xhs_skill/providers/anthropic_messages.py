from __future__ import annotations

import json
from collections.abc import AsyncIterator

from xhs_skill.core.errors import ProviderError
from xhs_skill.core.http_client import get_http_pool
from xhs_skill.schemas.provider import (
    GenerationRequest,
    GenerationResponse,
    ModelCapabilities,
    ModelEvent,
    ModelInfo,
)


class AnthropicMessagesProvider:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        default_model: str | None = None,
        *,
        name: str = "anthropic",
        anthropic_version: str = "2023-06-01",
    ) -> None:
        self.name = name
        self.api_key = api_key
        self.anthropic_version = anthropic_version
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model

    @property
    def headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": self.anthropic_version,
            "Content-Type": "application/json",
        }

    async def list_models(self) -> list[ModelInfo]:
        if not self.default_model:
            return []
        return [
            ModelInfo(
                provider=self.name,
                id=self.default_model,
                capabilities=await self.probe(self.default_model),
            )
        ]

    async def probe(self, model: str) -> ModelCapabilities:
        return ModelCapabilities(
            text=True, vision=True, streaming=True, tool_calling=True, json_mode=True
        )

    def _prompt(self, request: GenerationRequest) -> str:
        if not request.output_schema:
            return request.prompt
        return (
            f"{request.prompt}\n\n只输出符合以下 JSON Schema 的 JSON，不要输出 Markdown：\n"
            f"{json.dumps(request.output_schema, ensure_ascii=False)}"
        )

    def _payload(self, request: GenerationRequest, *, stream: bool = False) -> dict:
        return {
            "model": request.model or self.default_model,
            "system": request.system,
            "messages": [{"role": "user", "content": self._prompt(request)}],
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "stream": stream,
        }

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        try:
            client = await get_http_pool().get()
            response = await client.post(
                f"{self.base_url}/v1/messages",
                headers=self.headers,
                json=self._payload(request),
            )
            response.raise_for_status()
            raw = response.json()
            text = "".join(
                item.get("text", "")
                for item in raw.get("content", [])
                if item.get("type") == "text"
            )
            data = None
            if request.output_schema:
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    pass
            return GenerationResponse(
                text=text,
                data=data,
                provider=self.name,
                model=request.model,
                request_id=raw.get("id"),
                usage=raw.get("usage", {}),
            )
        except Exception as exc:
            raise ProviderError(f"Anthropic generation failed: {exc}") from exc

    async def stream(self, request: GenerationRequest) -> AsyncIterator[ModelEvent]:
        try:
            async with get_http_pool().stream(
                "POST",
                f"{self.base_url}/v1/messages",
                headers=self.headers,
                json=self._payload(request, stream=True),
                timeout=None,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line.removeprefix("data:").strip())
                    except json.JSONDecodeError:
                        continue
                    delta = event.get("delta", {}).get("text", "")
                    yield ModelEvent(type=event.get("type", "event"), delta=delta, data=event)
        except Exception as exc:
            raise ProviderError(f"Anthropic streaming failed: {exc}") from exc

    async def cancel(self, request_id: str) -> None:
        return None
