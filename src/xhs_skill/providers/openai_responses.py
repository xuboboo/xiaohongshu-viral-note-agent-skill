from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from xhs_skill.core.errors import ProviderError
from xhs_skill.core.http_client import get_http_pool
from xhs_skill.schemas.provider import (
    GenerationRequest,
    GenerationResponse,
    ModelCapabilities,
    ModelEvent,
    ModelInfo,
)


class OpenAIResponsesProvider:
    name = "openai"

    def __init__(self, api_key: str, base_url: str, default_model: str | None = None) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

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
            text=True,
            vision=True,
            streaming=True,
            tool_calling=True,
            structured_output=True,
            reasoning=True,
            web_search=True,
        )

    def _payload(self, request: GenerationRequest, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model or self.default_model,
            "instructions": request.system,
            "input": request.prompt,
            "stream": stream,
            "max_output_tokens": request.max_output_tokens,
        }
        if request.output_schema:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "xhs_delivery",
                    "strict": True,
                    "schema": request.output_schema,
                }
            }
        return payload

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        try:
            client = await get_http_pool().get()
            response = await client.post(
                f"{self.base_url}/responses",
                headers=self.headers,
                json=self._payload(request, False),
            )
            response.raise_for_status()
            payload = response.json()
            text = payload.get("output_text", "")
            if not text:
                chunks: list[str] = []
                for item in payload.get("output", []):
                    for content in item.get("content", []):
                        if content.get("type") in {"output_text", "text"}:
                            chunks.append(content.get("text", ""))
                text = "".join(chunks)
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
                request_id=payload.get("id"),
                usage=payload.get("usage", {}),
            )
        except Exception as exc:
            raise ProviderError(f"OpenAI Responses failed: {exc}") from exc

    async def stream(self, request: GenerationRequest) -> AsyncIterator[ModelEvent]:
        try:
            async with get_http_pool().stream(
                "POST",
                f"{self.base_url}/responses",
                headers=self.headers,
                json=self._payload(request, True),
                timeout=None,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line.removeprefix("data:").strip()
                    if raw == "[DONE]":
                        yield ModelEvent(type="done")
                        return
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    event_type = event.get("type", "event")
                    delta = event.get("delta", "") if event_type.endswith(".delta") else ""
                    yield ModelEvent(type=event_type, delta=delta, data=event)
        except Exception as exc:
            raise ProviderError(f"OpenAI Responses streaming failed: {exc}") from exc

    async def cancel(self, request_id: str) -> None:
        return None
