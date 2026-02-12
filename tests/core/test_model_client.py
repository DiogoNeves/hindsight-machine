from __future__ import annotations

import urllib.error

from proof_please.core.model_client import chat_with_model, list_available_models
from proof_please.pipeline.models import ModelBackendConfig


def test_list_available_models_returns_empty_after_successful_empty_probe(monkeypatch) -> None:
    def fake_request_json(url: str, timeout: float, method: str, payload=None):
        if url.endswith("/v1/models"):
            return {"data": []}
        if url.endswith("/api/tags"):
            raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("proof_please.core.model_client._request_json", fake_request_json)

    models = list_available_models(ModelBackendConfig(base_url="http://127.0.0.1:11434", timeout=30))

    assert models == []


def test_chat_with_model_falls_back_when_chat_payload_is_unparsable(monkeypatch) -> None:
    called_urls: list[str] = []

    def fake_request_json(url: str, timeout: float, method: str, payload=None):
        called_urls.append(url)
        if url.endswith("/v1/chat/completions"):
            return {"choices": [{"index": 0}]}
        if url.endswith("/api/chat"):
            return {"message": {"content": '{"claims": []}'}}
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("proof_please.core.model_client._request_json", fake_request_json)

    content = chat_with_model(
        config=ModelBackendConfig(base_url="http://127.0.0.1:11434", timeout=30),
        model="qwen3:4b",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert content == '{"claims": []}'
    assert called_urls == [
        "http://127.0.0.1:11434/v1/chat/completions",
        "http://127.0.0.1:11434/v1/chat/completions",
        "http://127.0.0.1:11434/api/chat",
    ]
