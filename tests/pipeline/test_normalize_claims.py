from __future__ import annotations

from proof_please.pipeline.normalize import normalize_claims


def test_normalize_claims_coerces_values_and_fallbacks() -> None:
    raw_claims = [
        {
            "speaker": "Host",
            "claim_text": "LDL causes heart disease",
            "evidence": [{"seg_id": "seg_000010", "quote": "LDL causes heart disease"}],
            "time_range_s": {"start": "100", "end": "90"},
            "claim_type": "not_real_type",
            "boldness_rating": "9",
        }
    ]
    start_time_by_seg_id = {"seg_000010": 123}

    rows = normalize_claims(
        doc_id="doc_1",
        model="qwen3:4b",
        raw_claims=raw_claims,
        start_time_by_seg_id=start_time_by_seg_id,
        run_id="run_test123",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["doc_id"] == "doc_1"
    assert row["claim_type"] == "other"
    assert row["boldness_rating"] == 3
    assert row["time_range_s"] == {"start": 100, "end": 100}
    assert row["provenance"]["run_id"] == "run_test123"
    assert row["provenance"]["step"] == "extract_claims"
    assert row["provenance"]["input_refs"] == ["seg_000010"]


def test_normalize_claims_skips_empty_claim_or_evidence() -> None:
    raw_claims = [
        {"speaker": "A", "claim_text": "", "evidence": [{"seg_id": "s1", "quote": "q"}]},
        {"speaker": "B", "claim_text": "x", "evidence": []},
    ]

    rows = normalize_claims(
        doc_id="doc_1",
        model="qwen3:4b",
        raw_claims=raw_claims,
        start_time_by_seg_id={},
        run_id="run_test123",
    )

    assert rows == []
