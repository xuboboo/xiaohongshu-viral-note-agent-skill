from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from typing import Protocol

from xhs_skill.core.config import Settings, get_settings
from xhs_skill.core.http_client import get_http_pool


class EmbeddingProvider(Protocol):
    name: str

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class HashingEmbeddingProvider:
    """Dependency-free character n-gram embedding fallback.

    It is deterministic and useful for offline safeguards, but reports itself as an
    approximate embedding provider rather than claiming neural semantic equivalence.
    """

    name = "hashing-ngram"

    def __init__(self, dimensions: int = 512) -> None:
        if dimensions < 64:
            raise ValueError("dimensions must be at least 64")
        self.dimensions = dimensions

    @staticmethod
    def _ngrams(text: str) -> list[str]:
        normalized = "".join(text.casefold().split())
        tokens: list[str] = []
        for size in (2, 3, 4):
            tokens.extend(normalized[index : index + size] for index in range(max(0, len(normalized) - size + 1)))
        return tokens or [normalized]

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for token in self._ngrams(text):
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
                index = int.from_bytes(digest[:8], "big") % self.dimensions
                sign = 1.0 if digest[8] & 1 else -1.0
                vector[index] += sign
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        return vectors


class OpenAICompatibleEmbeddingProvider:
    name = "openai-compatible-embeddings"

    def __init__(self, api_key: str, base_url: str, model: str, dimensions: int | None = None) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimensions = dimensions

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        payload: dict[str, object] = {"model": self.model, "input": list(texts)}
        if self.dimensions:
            payload["dimensions"] = self.dimensions
        client = await get_http_pool().get()
        response = await client.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json().get("data", [])
        ordered = sorted(data, key=lambda item: int(item.get("index", 0)))
        vectors = [list(map(float, item["embedding"])) for item in ordered]
        if len(vectors) != len(texts):
            raise RuntimeError("Embedding provider returned an unexpected vector count")
        return vectors


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    settings = settings or get_settings()
    provider = settings.embedding_provider.strip().lower()
    if provider in {"openai", "openai_compatible", "remote"}:
        api_key = settings.embedding_api_key or settings.openai_api_key
        if not api_key:
            raise ValueError("Embedding API key is required for a remote embedding provider")
        return OpenAICompatibleEmbeddingProvider(
            api_key=api_key,
            base_url=settings.embedding_base_url,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        )
    return HashingEmbeddingProvider(settings.embedding_dimensions)
