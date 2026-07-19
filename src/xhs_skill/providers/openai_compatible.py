from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx

from xhs_skill.core.errors import ProviderError
from xhs_skill.core.http_client import get_http_pool
from xhs_skill.schemas.provider import (
    GenerationRequest,
    GenerationResponse,
    ModelCapabilities,
    ModelEvent,
    ModelInfo,
)


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        default_model: str | None = None,
        timeout: float = 60.0,
        auth_header: str = "Authorization",
        auth_scheme: str = "Bearer",
        query_params: dict[str, str] | None = None,
        capabilities: ModelCapabilities | None = None,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model
        self.timeout = timeout
        self.auth_header = auth_header
        self.auth_scheme = auth_scheme
        self.query_params = query_params or {}
        self._capabilities = capabilities or ModelCapabilities(
            text=True, streaming=True, tool_calling=True, structured_output=True, json_mode=True
        )

    @property
    def headers(self) -> dict[str, str]:
        value = f"{self.auth_scheme} {self.api_key}".strip()
        return {self.auth_header: value, "Content-Type": "application/json"}

    async def list_models(self) -> list[ModelInfo]:
        try:
            client = await get_http_pool().get()
            response = await client.get(
                f"{self.base_url}/models",
                headers=self.headers,
                params=self.query_params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return [
                ModelInfo(
                    provider=self.name, id=item["id"], capabilities=await self.probe(item["id"])
                )
                for item in response.json().get("data", [])
            ]
        except Exception:
            if self.default_model:
                return [
                    ModelInfo(
                        provider=self.name,
                        id=self.default_model,
                        capabilities=await self.probe(self.default_model),
                    )
                ]
            return []

    async def probe(self, model: str) -> ModelCapabilities:
        return self._capabilities.model_copy(deep=True)

    def _payload(self, request: GenerationRequest, *, stream: bool) -> dict:
        payload: dict = {
            "model": request.model or self.default_model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.prompt},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            "stream": stream,
        }
        if request.output_schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "xhs_delivery",
                    "strict": True,
                    "schema": request.output_schema,
                },
            }
        return payload

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        request_id = str(uuid4())
        try:
            client = await get_http_pool().get()
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=self._payload(request, stream=False),
                params=self.query_params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            text = payload["choices"][0]["message"].get("content") or ""
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
                request_id=payload.get("id", request_id),
                usage=payload.get("usage", {}),
            )
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                f"{self.name} returned HTTP {exc.response.status_code}",
                details={"body": exc.response.text[:1000]},
            ) from exc
        except Exception as exc:
            raise ProviderError(f"{self.name} generation failed: {exc}") from exc

    async def stream(self, request: GenerationRequest) -> AsyncIterator[ModelEvent]:
        try:
            async with get_http_pool().stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json=self._payload(request, stream=True),
                params=self.query_params,
                timeout=None,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line.removeprefix("data:").strip()
                    if chunk == "[DONE]":
                        yield ModelEvent(type="done")
                        return
                    try:
                        payload = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    delta = payload.get("choices", [{}])[0].get("delta", {}).get("content") or ""
                    if delta:
                        yield ModelEvent(type="delta", delta=delta, data=payload)
        except Exception as exc:
            raise ProviderError(f"{self.name} streaming failed: {exc}") from exc

    async def cancel(self, request_id: str) -> None:
        return None
