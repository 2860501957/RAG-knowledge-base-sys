from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Protocol

from backend.config import Settings
from backend.services.text_utils import tokenize


class EmbeddingClient(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


@dataclass
class HashingEmbeddingClient:
    dimensions: int = 384

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in tokenize(text):
            digest = hashlib.sha1(token.encode("utf-8")).hexdigest()
            index = int(digest[:8], 16) % self.dimensions
            sign = 1.0 if int(digest[8:10], 16) % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]


@dataclass
class OpenAICompatibleEmbeddingClient:
    settings: Settings

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.settings.embedding_api_key:
            raise RuntimeError("EMBEDDING_API_KEY is required for remote embeddings")
        import requests

        embeddings: list[list[float]] = []
        batch_size = max(1, self.settings.embedding_batch_size)
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            try:
                response = requests.post(
                    f"{resolve_embedding_base_url(self.settings).rstrip('/')}/embeddings",
                    headers={
                        "Authorization": f"Bearer {self.settings.embedding_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"model": self.settings.embedding_model, "input": batch},
                    timeout=60,
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                status_code = getattr(getattr(exc, "response", None), "status_code", None)
                detail = getattr(getattr(exc, "response", None), "text", "")
                message = "Embedding request failed"
                if status_code:
                    message += f" with HTTP {status_code}"
                if detail:
                    message += f": {detail[:300]}"
                raise RuntimeError(message) from None

            payload = response.json()
            embeddings.extend(item["embedding"] for item in payload["data"])
        return embeddings


def create_embedding_client(settings: Settings) -> EmbeddingClient:
    if settings.embedding_provider.lower() in {"openai", "api", "siliconflow", "jina"}:
        return OpenAICompatibleEmbeddingClient(settings)
    return HashingEmbeddingClient()


def resolve_embedding_base_url(settings: Settings) -> str:
    if settings.embedding_provider.lower() == "hash":
        return "local-hash"
    if settings.embedding_base_url.strip():
        return settings.embedding_base_url.strip()
    provider = settings.embedding_provider.lower()
    defaults = {
        "openai": "https://api.openai.com/v1",
        "siliconflow": "https://api.siliconflow.cn/v1",
        "jina": "https://api.jina.ai/v1",
    }
    return defaults.get(provider, settings.llm_base_url)
