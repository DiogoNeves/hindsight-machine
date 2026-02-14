"""Top-level orchestration helpers for the health-claim pipeline."""

from __future__ import annotations

import urllib.error
from uuid import uuid4
from collections.abc import Callable
from pathlib import Path
from typing import Any

from proof_please.core.io import load_transcript
from proof_please.core.model_client import list_available_models
from proof_please.pipeline.extract_claims import extract_claims_for_models
from proof_please.pipeline.generate_queries import choose_query_model, generate_validation_queries
from proof_please.pipeline.models import ModelBackendConfig


def parse_model_list(models: str) -> list[str]:
    """Parse comma-separated model list."""
    return [model.strip() for model in models.split(",") if model.strip()]


def validate_common_args(timeout: float, max_segments: int) -> None:
    """Validate shared runtime parameters."""
    if timeout <= 0:
        raise ValueError("--timeout must be > 0")
    if max_segments < 0:
        raise ValueError("--max-segments must be >= 0")


def validate_path_exists(path: Path, flag_name: str) -> None:
    """Validate path existence for CLI options."""
    if not path.exists():
        raise FileNotFoundError(f"{flag_name} path does not exist: {path}")


def fetch_available_models(config: ModelBackendConfig) -> list[str]:
    """Fetch available local models with user-friendly errors."""
    try:
        return list_available_models(config)
    except urllib.error.URLError as exc:
        raise ConnectionError(f"Could not connect to model backend at {config.base_url}: {exc}") from exc


def find_missing_models(requested_models: list[str], available_models: list[str]) -> list[str]:
    """Return model names requested by user but absent from backend list."""
    return [name for name in requested_models if name not in available_models]


def run_claim_extraction(
    transcript: Path,
    model_list: list[str],
    config: ModelBackendConfig,
    max_segments: int,
    chunk_size: int,
    chunk_overlap: int,
    on_status: Callable[[str], None] | None = None,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Run transcript claim extraction and return deduplicated claim rows."""
    if not model_list:
        raise ValueError("No models provided.")

    run_id = run_id or f"run_{uuid4().hex[:12]}"
    validate_path_exists(transcript, "--transcript")
    validate_common_args(timeout=config.timeout, max_segments=max_segments)

    doc_id, segments = load_transcript(transcript)
    if max_segments > 0:
        segments = segments[:max_segments]

    return extract_claims_for_models(
        doc_id=doc_id,
        segments=segments,
        model_list=model_list,
        config=config,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        on_status=on_status,
        run_id=run_id,
    )


def run_query_generation(
    claims: list[dict[str, Any]],
    config: ModelBackendConfig,
    query_model: str | None,
    model_list: list[str],
    available_models: list[str],
    chunk_size: int,
    chunk_overlap: int,
    on_status: Callable[[str], None] | None = None,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Generate validation queries from existing claim rows."""

    def emit(message: str) -> None:
        if on_status:
            on_status(message)

    run_id = run_id or f"run_{uuid4().hex[:12]}"

    selected_query_model = choose_query_model(
        query_model=query_model,
        model_list=model_list,
        available_models=available_models,
    )
    if selected_query_model is None:
        emit(
            "Skipping query generation: no model available. "
            "Use --query-model or install a local model."
        )
        return []

    emit(f"Generating validation queries with: {selected_query_model}")
    return generate_validation_queries(
        claims=claims,
        config=config,
        query_model=selected_query_model,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        on_status=on_status,
        run_id=run_id,
    )
