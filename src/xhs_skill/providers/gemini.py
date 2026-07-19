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


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, base_url: str, default_model: str | None = None) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model

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
            text=True, vision=True, streaming=True, tool_calling=True, structured_output=True
        )

    def _payload(self, request: GenerationRequest) -> dict:
        config: dict = {
            "temperature": request.temperature,
            "maxOutputTokens": request.max_output_tokens,
        }
        if request.output_schema:
            config["responseMimeType"] = "application/json"
            config["responseJsonSchema"] = request.output_schema
        return {
            "systemInstruction": {"parts": [{"text": request.system}]},
            "contents": [{"role": "user", "parts": [{"text": request.prompt}]}],
            "generationConfig": config,
        }

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        model = request.model or self.default_model
        url = f"{self.base_url}/v1beta/models/{model}:generateContent?key={self.api_key}"
        try:
            client = await get_http_pool().get()
            response = await client.post(url, json=self._payload(request))
            response.raise_for_status()
            raw = response.json()
            text = raw["candidates"][0]["content"]["parts"][0].get("text", "")
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
                model=model or "",
                usage=raw.get("usageMetadata", {}),
            )
        except Exception as exc:
            raise ProviderError(f"Gemini generation failed: {exc}") from exc

    async def stream(self, request: GenerationRequest) -> AsyncIterator[ModelEvent]:
        model = request.model or self.default_model
        url = f"{self.base_url}/v1beta/models/{model}:streamGenerateContent?alt=sse&key={self.api_key}"
        try:
            async with get_http_pool().stream(
                "POST",
                url,
                json=self._payload(request),
                timeout=None,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        event = json.loads(line.removeprefix("data:").strip())
                        delta = event["candidates"][0]["content"]["parts"][0].get("text", "")
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    yield ModelEvent(type="delta", delta=delta, data=event)
        except Exception as exc:
            raise ProviderError(f"Gemini streaming failed: {exc}") from exc

    async def cancel(self, request_id: str) -> None:
        return None
