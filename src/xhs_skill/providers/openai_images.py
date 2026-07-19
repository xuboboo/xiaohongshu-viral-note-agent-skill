"""OpenAI / 通义兼容图片生成 Provider（Images API / GPT Image 族）。

失败由调用方捕获；无 key 时 NoOp。
- openai: https://api.openai.com/v1/images/generations
- dashscope/qwen: compatible-mode 网关
DALL·E 路径在 2026 逐步 sunset；OpenAI 默认 gpt-image-1，通义默认 qwen-image-plus。
"""
from __future__ import annotations

import base64
import binascii
from pathlib import Path
from uuid import uuid4

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.http_client import get_http_pool
from xhs_skill.core.identifiers import atomic_write_private, private_mkdir
from xhs_skill.providers.base import ImageResult, NoOpImageProvider

_DASHSCOPE_COMPAT_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_DASHSCOPE_DEFAULT_MODEL = "qwen-image-plus"
_OPENAI_DEFAULT_MODEL = "gpt-image-1"


class OpenAICompatibleImageProvider:
    name = "openai_compatible_images"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        output_dir: Path | None = None,
        vendor: str = "openai",
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.vendor = vendor
        self.output_dir = private_mkdir(output_dir or Path("./data/generated-images"))

    async def generate_cover(
        self,
        prompt: str,
        *,
        width: int = 1080,
        height: int = 1440,
    ) -> ImageResult:
        size = "1024x1536" if height >= width else "1536x1024"
        if width == height:
            size = "1024x1024"
        payload: dict = {
            "model": self.model,
            "prompt": prompt[:4000],
            "n": 1,
            "size": size,
        }
        # OpenAI 族优先 b64；兼容网关可能忽略未知字段
        if self.vendor in {"openai", "openai_compatible", "remote", "gpt_image"}:
            payload["response_format"] = "b64_json"

        client = await get_http_pool().get()
        response = await client.post(
            f"{self.base_url}/images/generations",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
            timeout=120.0,
        )
        response.raise_for_status()
        data = response.json().get("data") or []
        if not data:
            raise RuntimeError("Image provider returned empty data")
        item = data[0]
        raw = self._decode_b64(item)
        if raw is None and item.get("url"):
            raw = await self._download(str(item["url"]))
        if not raw:
            raise RuntimeError("Image provider did not return image bytes")
        path = self.output_dir / f"cover-{uuid4().hex}.png"
        atomic_write_private(path, raw)
        return ImageResult(path=path, width=width, height=height, media_type="image/png")

    @staticmethod
    def _decode_b64(item: dict) -> bytes | None:
        b64 = item.get("b64_json") or item.get("b64")
        if not b64:
            return None
        try:
            raw = base64.b64decode(b64)
            return raw or None
        except (binascii.Error, ValueError):
            return None

    @staticmethod
    async def _download(url: str) -> bytes:
        client = await get_http_pool().get()
        response = await client.get(url, timeout=120.0)
        response.raise_for_status()
        content = response.content
        if not content:
            raise RuntimeError("Image URL download returned empty body")
        return content


def _resolve_image_backend(settings: Settings) -> tuple[str, str | None, str, str]:
    """返回 (vendor, api_key, base_url, model)。"""
    explicit = (settings.image_provider or "auto").strip().lower()
    image_key = settings.image_api_key
    openai_key = settings.openai_api_key
    dash_key = settings.dashscope_api_key

    if explicit in {"noop", "none", "off"}:
        return "noop", None, "", ""

    if explicit in {"openai", "openai_compatible", "remote", "gpt_image"}:
        return (
            "openai",
            image_key or openai_key,
            settings.image_base_url or "https://api.openai.com/v1",
            settings.image_model or _OPENAI_DEFAULT_MODEL,
        )

    if explicit in {"dashscope", "qwen", "tongyi", "wanx"}:
        return (
            "dashscope",
            image_key or dash_key,
            settings.image_base_url
            or settings.dashscope_base_url
            or _DASHSCOPE_COMPAT_BASE,
            settings.image_model or _DASHSCOPE_DEFAULT_MODEL,
        )

    # auto：image_api_key → openai → dashscope
    if image_key:
        base = settings.image_base_url or "https://api.openai.com/v1"
        vendor = "dashscope" if "dashscope" in base else "openai"
        model = settings.image_model or (
            _DASHSCOPE_DEFAULT_MODEL if vendor == "dashscope" else _OPENAI_DEFAULT_MODEL
        )
        return vendor, image_key, base, model
    if openai_key:
        return (
            "openai",
            openai_key,
            settings.image_base_url or "https://api.openai.com/v1",
            settings.image_model or _OPENAI_DEFAULT_MODEL,
        )
    if dash_key:
        return (
            "dashscope",
            dash_key,
            settings.image_base_url
            or settings.dashscope_base_url
            or _DASHSCOPE_COMPAT_BASE,
            settings.image_model or _DASHSCOPE_DEFAULT_MODEL,
        )
    return "noop", None, "", ""


def get_image_provider(settings: Settings | None = None):
    """根据配置返回 ImageProvider；未配置时 NoOp。

    image_provider:
      - noop / none / off — 强制关闭
      - auto — 探测 image_api_key / openai_api_key / dashscope_api_key
      - openai / openai_compatible
      - dashscope / qwen / tongyi
    """
    settings = settings or get_settings()
    mode = (settings.image_provider or "auto").strip().lower()
    if mode in {"noop", "none", "off"}:
        return NoOpImageProvider()

    vendor, api_key, base_url, model = _resolve_image_backend(settings)
    if vendor == "noop" or not api_key:
        return NoOpImageProvider()

    return OpenAICompatibleImageProvider(
        api_key=api_key,
        base_url=base_url,
        model=model,
        output_dir=settings.image_output_dir,
        vendor=vendor,
    )