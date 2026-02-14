from __future__ import annotations

from proof_please.pipeline.normalize import generate_heuristic_queries, naturalize_query_question


def test_naturalize_query_question_rewrites_repetitive_prefix() -> None:
    query = (
        "What is the current scientific consensus on whether "
        "LDL cholesterol is an independent risk factor for heart disease?"
    )

    naturalized = naturalize_query_question(query)

    assert naturalized == "LDL cholesterol is an independent risk factor for heart disease?"


def test_generate_heuristic_queries_returns_non_empty_for_valid_claim() -> None:
    claims = [
        {
            "claim_id": "clm_000001",
            "claim_text": "Higher LDL cholesterol increases cardiovascular risk",
            "claim_type": "medical_risk",
        }
    ]

    rows = generate_heuristic_queries(claims, run_id="run_test456")

    assert len(rows) == 1
    row = rows[0]
    assert row["claim_id"] == "clm_000001"
    assert row["query"]
    assert row["why_this_query"]
    assert "systematic review" in row["preferred_sources"]
    assert row["provenance"]["run_id"] == "run_test456"
    assert row["provenance"]["input_refs"] == ["clm_000001"]
