from __future__ import annotations

from proof_please.explorer.linking import (
    compute_link_diagnostics,
    group_queries_by_claim_id,
    resolve_claim_evidence,
)
from proof_please.explorer.models import ClaimRow, QueryRow
from proof_please.pipeline.models import TranscriptDocument


def _build_claim(
    claim_id: str,
    doc_id: str,
    seg_ids: list[str],
) -> ClaimRow:
    return ClaimRow.model_validate(
        {
            "claim_id": claim_id,
            "doc_id": doc_id,
            "speaker": "Host",
            "claim_text": f"Claim {claim_id}",
            "claim_type": "medical_risk",
            "model": "qwen3:4b",
            "evidence": [{"seg_id": seg_id, "quote": f"Quote for {seg_id}"} for seg_id in seg_ids],
        }
    )


def _build_query(claim_id: str, query: str) -> QueryRow:
    return QueryRow.model_validate(
        {
            "claim_id": claim_id,
            "query": query,
            "why_this_query": "Because it checks the claim.",
            "preferred_sources": ["systematic review"],
        }
    )


def _build_transcript(doc_id: str) -> TranscriptDocument:
    return TranscriptDocument.model_validate(
        {
            "doc_id": doc_id,
            "segments": [
                {
                    "seg_id": "seg_000001",
                    "speaker": "Host",
                    "start_time_s": 10,
                    "text": "LDL cholesterol matters.",
                },
                {
                    "seg_id": "seg_000002",
                    "speaker": "Guest",
                    "start_time_s": 20,
                    "text": "Fiber can help lower LDL.",
                },
            ],
        }
    )


def test_group_queries_by_claim_id_groups_rows() -> None:
    queries = [
        _build_query("clm_1", "Is LDL a risk factor?"),
        _build_query("clm_1", "Does lowering LDL reduce risk?"),
        _build_query("clm_2", "Does fiber lower LDL?"),
    ]

    grouped = group_queries_by_claim_id(queries)

    assert set(grouped) == {"clm_1", "clm_2"}
    assert len(grouped["clm_1"]) == 2
    assert len(grouped["clm_2"]) == 1


def test_resolve_claim_evidence_marks_missing_segment() -> None:
    claim = _build_claim("clm_1", "doc_1", ["seg_000001", "seg_999999"])
    transcripts = {"doc_1": _build_transcript("doc_1")}

    resolved = resolve_claim_evidence(claim, transcripts)

    assert len(resolved) == 2
    assert resolved[0].found is True
    assert resolved[0].speaker == "Host"
    assert resolved[1].found is False
    assert resolved[1].seg_id == "seg_999999"


def test_compute_link_diagnostics_reports_join_issues() -> None:
    claims = [
        _build_claim("clm_1", "doc_1", ["seg_000001"]),
        _build_claim("clm_2", "doc_missing", ["seg_000001"]),
        _build_claim("clm_3", "doc_1", ["seg_404404"]),
    ]
    queries = [
        _build_query("clm_1", "Is LDL an independent risk factor?"),
        _build_query("clm_orphan", "Should this orphan query be reviewed?"),
    ]
    transcripts = {"doc_1": _build_transcript("doc_1")}

    diagnostics = compute_link_diagnostics(claims, queries, transcripts)

    assert diagnostics.total_claims == 3
    assert diagnostics.total_queries == 2
    assert diagnostics.total_transcript_docs == 1
    assert len(diagnostics.orphan_queries) == 1
    assert diagnostics.orphan_queries[0].claim_id == "clm_orphan"
    assert {row.claim_id for row in diagnostics.claims_without_queries} == {"clm_2", "clm_3"}
    assert [row.claim_id for row in diagnostics.claims_missing_transcript_doc] == ["clm_2"]
    assert len(diagnostics.missing_evidence_links) == 1
    assert diagnostics.missing_evidence_links[0].claim_id == "clm_3"
