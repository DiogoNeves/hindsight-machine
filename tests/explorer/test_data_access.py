from __future__ import annotations

import json
from pathlib import Path

import pytest

from proof_please.explorer.data_access import load_dataset


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row))
            file.write("\n")


def test_load_dataset_parses_rows_and_collects_warnings(tmp_path: Path) -> None:
    claims_path = tmp_path / "claims.jsonl"
    queries_path = tmp_path / "queries.jsonl"
    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir(parents=True)

    _write_jsonl(
        claims_path,
        [
            {
                "claim_id": "clm_1",
                "doc_id": "doc_1",
                "speaker": "Host",
                "claim_text": "LDL is a risk factor",
                "evidence": [{"seg_id": "seg_000001", "quote": "LDL is a risk factor."}],
            },
            {
                "doc_id": "doc_1",
                "claim_text": "Missing claim id should be skipped",
            },
        ],
    )
    _write_jsonl(
        queries_path,
        [
            {
                "claim_id": "clm_1",
                "query": "Is LDL an independent risk factor?",
                "why_this_query": "Checks the cardiovascular risk claim.",
            }
        ],
    )

    transcript_payload = {
        "doc_id": "doc_1",
        "segments": [
            {
                "seg_id": "seg_000001",
                "speaker": "Host",
                "start_time_s": 12,
                "text": "LDL is a risk factor.",
            }
        ],
    }
    (transcripts_dir / "doc_1.json").write_text(json.dumps(transcript_payload), encoding="utf-8")

    dataset = load_dataset(claims_path, queries_path, transcripts_dir)

    assert len(dataset.claims) == 1
    assert dataset.claims[0].claim_id == "clm_1"
    assert len(dataset.queries) == 1
    assert set(dataset.transcripts_by_doc_id) == {"doc_1"}
    assert any(message.startswith("Skipped invalid claim row 2") for message in dataset.warnings)


def test_load_dataset_raises_when_queries_file_missing(tmp_path: Path) -> None:
    claims_path = tmp_path / "claims.jsonl"
    claims_path.write_text("", encoding="utf-8")
    transcripts_dir = tmp_path / "transcripts"
    transcripts_dir.mkdir(parents=True)

    with pytest.raises(FileNotFoundError, match="Queries path does not exist"):
        load_dataset(
            claims_path=claims_path,
            queries_path=tmp_path / "missing_queries.jsonl",
            transcripts_path=transcripts_dir,
        )
