from __future__ import annotations

from backend.config import Settings
from backend.services.embeddings import (
    OpenAICompatibleEmbeddingClient,
    resolve_embedding_base_url,
)


class FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_siliconflow_embedding_uses_provider_default_base_url() -> None:
    settings = Settings(
        embedding_provider="siliconflow",
        embedding_api_key="test-key",
        embedding_model="BAAI/bge-m3",
        llm_base_url="https://api.deepseek.com",
    )

    assert resolve_embedding_base_url(settings) == "https://api.siliconflow.cn/v1"


def test_remote_embedding_client_uses_embedding_credentials(monkeypatch) -> None:
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse({"data": [{"embedding": [0.1, 0.2, 0.3]}]})

    import requests

    monkeypatch.setattr(requests, "post", fake_post)
    settings = Settings(
        llm_api_key="deepseek-key",
        llm_base_url="https://api.deepseek.com",
        embedding_provider="api",
        embedding_api_key="embedding-key",
        embedding_base_url="https://embedding.example.com/v1",
        embedding_model="embedding-model",
    )

    vectors = OpenAICompatibleEmbeddingClient(settings).embed(["测试文本"])

    assert vectors == [[0.1, 0.2, 0.3]]
    assert captured["url"] == "https://embedding.example.com/v1/embeddings"
    assert captured["headers"]["Authorization"] == "Bearer embedding-key"
    assert captured["json"] == {"model": "embedding-model", "input": ["测试文本"]}
