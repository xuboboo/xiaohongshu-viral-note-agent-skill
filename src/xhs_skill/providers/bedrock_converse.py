from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from xhs_skill.core.errors import ConfigurationError, ProviderError
from xhs_skill.schemas.provider import (
    GenerationRequest,
    GenerationResponse,
    ModelCapabilities,
    ModelEvent,
    ModelInfo,
)


class BedrockConverseProvider:
    name = "bedrock"

    def __init__(self, region: str, default_model: str | None = None) -> None:
        try:
            import boto3
        except ImportError as exc:
            raise ConfigurationError("Install the 'aws' extra to use Amazon Bedrock") from exc
        self.client = boto3.client("bedrock-runtime", region_name=region)
        self.default_model = default_model

    async def list_models(self) -> list[ModelInfo]:
        return (
            [
                ModelInfo(
                    provider=self.name,
                    id=self.default_model,
                    capabilities=await self.probe(self.default_model),
                )
            ]
            if self.default_model
            else []
        )

    async def probe(self, model: str) -> ModelCapabilities:
        return ModelCapabilities(text=True, vision=True, streaming=True, tool_calling=True)

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        model = request.model or self.default_model
        if not model:
            raise ProviderError("Bedrock model is required")
        prompt = request.prompt
        if request.output_schema:
            import json

            prompt += "\n\nReturn JSON matching this schema:\n" + json.dumps(
                request.output_schema, ensure_ascii=False
            )

        def call():
            return self.client.converse(
                modelId=model,
                system=[{"text": request.system}],
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={
                    "maxTokens": request.max_output_tokens,
                    "temperature": request.temperature,
                },
            )

        try:
            raw = await asyncio.to_thread(call)
            text = "".join(item.get("text", "") for item in raw["output"]["message"]["content"])
            data = None
            if request.output_schema:
                import json

                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    pass
            return GenerationResponse(
                text=text,
                data=data,
                provider=self.name,
                model=model,
                usage=raw.get("usage", {}),
            )
        except Exception as exc:
            raise ProviderError(f"Bedrock Converse failed: {exc}") from exc

    async def stream(self, request: GenerationRequest) -> AsyncIterator[ModelEvent]:
        # boto3's event stream is blocking; bridge it through a worker thread and queue.
        model = request.model or self.default_model
        if not model:
            raise ProviderError("Bedrock model is required")
        queue: asyncio.Queue[object] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        sentinel = object()

        def worker() -> None:
            try:
                response = self.client.converse_stream(
                    modelId=model,
                    system=[{"text": request.system}],
                    messages=[{"role": "user", "content": [{"text": request.prompt}]}],
                    inferenceConfig={
                        "maxTokens": request.max_output_tokens,
                        "temperature": request.temperature,
                    },
                )
                for event in response["stream"]:
                    delta = event.get("contentBlockDelta", {}).get("delta", {}).get("text", "")
                    if delta:
                        asyncio.run_coroutine_threadsafe(queue.put(delta), loop)
            except Exception as exc:
                asyncio.run_coroutine_threadsafe(queue.put(exc), loop)
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(sentinel), loop)

        asyncio.create_task(asyncio.to_thread(worker))
        while True:
            item = await queue.get()
            if item is sentinel:
                yield ModelEvent(type="done")
                return
            if isinstance(item, Exception):
                raise ProviderError(f"Bedrock streaming failed: {item}")
            yield ModelEvent(type="delta", delta=str(item))

    async def cancel(self, request_id: str) -> None:
        return None
