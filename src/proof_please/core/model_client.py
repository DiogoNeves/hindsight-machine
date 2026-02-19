"""Model-backend client helpers."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from proof_please.pipeline.models import ModelBackendConfig


def _endpoint(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def _request_json(url: str, timeout: float, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.load(resp)
    if not isinstance(body, dict):
        raise ValueError("Model backend returned non-object JSON response.")
    return body


def _parse_model_names(payload: dict[str, Any]) -> list[str]:
    data = payload.get("data")
    if isinstance(data, list):
        names: list[str] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            name = item.get("id") or item.get("name") or item.get("model")
            if isinstance(name, str) and name:
                names.append(name)
        return names

    models = payload.get("models")
    if isinstance(models, list):
        names = []
        for model in models:
            if not isinstance(model, dict):
                continue
            name = model.get("name") or model.get("model") or model.get("id")
            if isinstance(name, str) and name:
                names.append(name)
        return names
    return []


def list_available_models(config: ModelBackendConfig) -> list[str]:
    """Fetch available model names from OpenAI-compatible or legacy endpoints."""
    endpoints = ("/v1/models", "/api/tags")
    last_http_error: urllib.error.HTTPError | None = None
    had_successful_probe = False
    for path in endpoints:
        try:
            payload = _request_json(
                url=_endpoint(config.base_url, path),
                timeout=config.timeout,
                method="GET",
            )
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                last_http_error = exc
                continue
            raise
        had_successful_probe = True
        names = _parse_model_names(payload)
        if names:
            return names
    if had_successful_probe:
        return []
    if last_http_error is not None:
        raise last_http_error
    return []


def _extract_chat_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first_choice = choices[0]
        if isinstance(first_choice, dict):
            message = first_choice.get("message", {})
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content

    message = payload.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content

    top_level_content = payload.get("response")
    if isinstance(top_level_content, str) and top_level_content.strip():
        return top_level_content

    top_level_text = payload.get("text")
    if isinstance(top_level_text, str) and top_level_text.strip():
        return top_level_text

    raise ValueError("Model backend response missing message content.")


def chat_with_model(
    config: ModelBackendConfig,
    model: str,
    messages: list[dict[str, str]],
) -> str:
    """Call the model backend and return chat-completion text."""
    openai_payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 1200,
        "response_format": {"type": "json_object"},
    }
    legacy_payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "format": "json",
        "options": {"temperature": 0.0, "num_predict": 1200},
    }

    openai_payload_no_format = {
        "model": model,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": 1200,
    }
    endpoints: list[tuple[str, dict[str, Any]]] = [
        ("/v1/chat/completions", openai_payload),
        ("/v1/chat/completions", openai_payload_no_format),
        ("/api/chat", legacy_payload),
    ]
    last_http_error: urllib.error.HTTPError | None = None
    last_content_error: ValueError | None = None
    had_successful_probe = False
    for path, payload in endpoints:
        try:
            response = _request_json(
                url=_endpoint(config.base_url, path),
                timeout=config.timeout,
                method="POST",
                payload=payload,
            )
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404):
                last_http_error = exc
                continue
            raise
        had_successful_probe = True
        try:
            return _extract_chat_content(response)
        except ValueError as exc:
            last_content_error = exc
            continue

    if had_successful_probe and last_content_error is not None:
        raise last_content_error
    if last_http_error is not None:
        raise last_http_error
    raise ValueError("Failed to call model backend.")
