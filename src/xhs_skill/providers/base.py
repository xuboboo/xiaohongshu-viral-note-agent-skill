from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from xhs_skill.schemas.provider import (
    GenerationRequest,
    GenerationResponse,
    ModelCapabilities,
    ModelEvent,
    ModelInfo,
)


class ModelProvider(Protocol):
    name: str

    async def list_models(self) -> list[ModelInfo]: ...

    async def probe(self, model: str) -> ModelCapabilities: ...

    async def generate(self, request: GenerationRequest) -> GenerationResponse: ...

    def stream(self, request: GenerationRequest) -> AsyncIterator[ModelEvent]: ...

    async def cancel(self, request_id: str) -> None: ...


@dataclass
class ImageResult:
    """图片生成结果。"""
    path: Path
    width: int
    height: int
    media_type: str = "image/png"


class ImageProvider(Protocol):
    """可选的封面/配图生成接口。

    实现可选；失败不影响正文交付。
    """
    name: str

    async def generate_cover(
        self,
        prompt: str,
        *,
        width: int = 1080,
        height: int = 1440,
    ) -> ImageResult: ...


class NoOpImageProvider:
    """默认无操作实现：总是失败，由调用方捕获后跳过。"""
    name: str = "noop"

    async def generate_cover(
        self,
        prompt: str,
        *,
        width: int = 1080,
        height: int = 1440,
    ) -> ImageResult:
        raise NotImplementedError("No image provider configured; cover generation skipped")