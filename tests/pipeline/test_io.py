from __future__ import annotations

import json
from pathlib import Path

import pytest

from proof_please.core.io import load_claims_jsonl, load_transcript, write_jsonl


def test_write_and_load_claims_jsonl_roundtrip(tmp_path: Path) -> None:
    output = tmp_path / "claims.jsonl"
    rows = [
        {"claim_id": "clm_000001", "claim_text": "LDL risk"},
        {"claim_id": "clm_000002", "claim_text": "Fiber benefit"},
    ]

    write_jsonl(output, rows)
    loaded = load_claims_jsonl(output)

    assert loaded == rows


def test_load_transcript_validates_required_fields(tmp_path: Path) -> None:
    path = tmp_path / "transcript.json"
    payload = {
        "doc_id": "doc_1",
        "segments": [{"seg_id": "seg_000001", "speaker": "Host", "start_time_s": 1, "text": "x"}],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    doc_id, segments = load_transcript(path)

    assert doc_id == "doc_1"
    assert segments[0]["seg_id"] == "seg_000001"


def test_load_transcript_errors_when_missing_segments(tmp_path: Path) -> None:
    path = tmp_path / "transcript_missing_segments.json"
    path.write_text(json.dumps({"doc_id": "doc_1", "segments": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="Transcript JSON missing segments"):
        load_transcript(path)
