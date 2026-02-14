from __future__ import annotations

from pathlib import Path

import pytest

from proof_please.pipeline.models import ModelBackendConfig
from proof_please.pipeline.pipeline_runner import run_claim_extraction, run_query_generation


def test_run_claim_extraction_orchestrates_stage(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_load_transcript(path: Path):
        assert path == Path("transcript.json")
        return "doc_1", [
            {"seg_id": "seg_000001", "start_time_s": 1, "speaker": "A", "text": "x"},
            {"seg_id": "seg_000002", "start_time_s": 2, "speaker": "A", "text": "y"},
        ]

    def fake_extract_claims_for_models(**kwargs):
        captured.update(kwargs)
        return [{"claim_id": "clm_000001", "claim_text": "x"}]

    monkeypatch.setattr("proof_please.pipeline.pipeline_runner.validate_path_exists", lambda *args: None)
    monkeypatch.setattr("proof_please.pipeline.pipeline_runner.load_transcript", fake_load_transcript)
    monkeypatch.setattr(
        "proof_please.pipeline.pipeline_runner.extract_claims_for_models",
        fake_extract_claims_for_models,
    )

    rows = run_claim_extraction(
        transcript=Path("transcript.json"),
        model_list=["qwen3:4b"],
        config=ModelBackendConfig(base_url="http://127.0.0.1:11434", timeout=30),
        max_segments=1,
        chunk_size=4,
        chunk_overlap=1,
    )

    assert rows == [{"claim_id": "clm_000001", "claim_text": "x"}]
    assert captured["doc_id"] == "doc_1"
    assert len(captured["segments"]) == 1
    assert isinstance(captured["run_id"], str)
    assert captured["run_id"].startswith("run_")


def test_run_query_generation_skips_when_no_model(monkeypatch) -> None:
    monkeypatch.setattr("proof_please.pipeline.pipeline_runner.choose_query_model", lambda **kwargs: None)

    rows = run_query_generation(
        claims=[{"claim_id": "clm_000001", "claim_text": "x"}],
        config=ModelBackendConfig(base_url="http://127.0.0.1:11434", timeout=30),
        query_model=None,
        model_list=["qwen3:4b"],
        available_models=[],
        chunk_size=10,
        chunk_overlap=1,
    )

    assert rows == []


def test_run_query_generation_uses_selected_model(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_choose(**kwargs):
        return "qwen3:4b"

    def fake_generate_validation_queries(**kwargs):
        captured.update(kwargs)
        return [{"claim_id": "clm_000001", "query": "Is x?"}]

    monkeypatch.setattr("proof_please.pipeline.pipeline_runner.choose_query_model", fake_choose)
    monkeypatch.setattr(
        "proof_please.pipeline.pipeline_runner.generate_validation_queries",
        fake_generate_validation_queries,
    )

    rows = run_query_generation(
        claims=[{"claim_id": "clm_000001", "claim_text": "x"}],
        config=ModelBackendConfig(base_url="http://127.0.0.1:11434", timeout=30),
        query_model=None,
        model_list=["qwen3:4b"],
        available_models=["qwen3:4b"],
        chunk_size=10,
        chunk_overlap=1,
    )

    assert rows == [{"claim_id": "clm_000001", "query": "Is x?"}]
    assert captured["query_model"] == "qwen3:4b"
    assert isinstance(captured["run_id"], str)
    assert captured["run_id"].startswith("run_")


def test_run_claim_extraction_rejects_empty_models() -> None:
    with pytest.raises(ValueError, match="No models provided"):
        run_claim_extraction(
            transcript=Path("transcript.json"),
            model_list=[],
            config=ModelBackendConfig(base_url="http://127.0.0.1:11434", timeout=30),
            max_segments=0,
            chunk_size=10,
            chunk_overlap=1,
        )
