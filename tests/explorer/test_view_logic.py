from __future__ import annotations

from proof_please.explorer.models import ClaimRow, QueryRow
from proof_please.explorer.view_logic import (
    build_claims_to_queries_index,
    build_episode_claim_rows,
    build_segment_to_claims_index,
    build_source_episode_index,
    build_source_summary,
    default_claim_for_segment,
    filter_episode_claim_rows,
)
from proof_please.pipeline.models import TranscriptDocument


def _build_claim(
    claim_id: str,
    doc_id: str,
    *,
    speaker: str = "Host",
    claim_type: str = "medical_risk",
    boldness_rating: int | None = None,
    evidence_seg_ids: list[str] | None = None,
) -> ClaimRow:
    evidence_seg_ids = evidence_seg_ids or ["seg_000001"]
    return ClaimRow.model_validate(
        {
            "claim_id": claim_id,
            "doc_id": doc_id,
            "speaker": speaker,
            "claim_text": f"Claim text {claim_id}",
            "claim_type": claim_type,
            "boldness_rating": boldness_rating,
            "model": "qwen3:4b",
            "evidence": [
                {"seg_id": seg_id, "quote": f"quote {seg_id}"}
                for seg_id in evidence_seg_ids
            ],
        }
    )


def _build_query(claim_id: str, query: str) -> QueryRow:
    return QueryRow.model_validate(
        {
            "claim_id": claim_id,
            "query": query,
            "why_this_query": "Checks the claim.",
            "preferred_sources": ["systematic review"],
        }
    )


def _build_transcript(
    doc_id: str,
    *,
    source: dict[str, object] | None = None,
    episode: dict[str, object] | None = None,
) -> TranscriptDocument:
    return TranscriptDocument.model_validate(
        {
            "doc_id": doc_id,
            "source": source or {},
            "episode": episode or {},
            "segments": [],
        }
    )


def test_build_source_episode_index_groups_and_sorts_by_episode_title() -> None:
    transcripts = {
        "doc_1": _build_transcript(
            "doc_1",
            source={"url": "https://www.alpha.fm/episode/1"},
            episode={"title": "Zulu Episode", "published_date": "2024-01-01"},
        ),
        "doc_2": _build_transcript(
            "doc_2",
            source={"url": "https://alpha.fm/episode/2"},
            episode={"title": "Alpha Episode", "published_date": "2024-02-02"},
        ),
        "doc_3": _build_transcript(
            "doc_3",
            source={"type": "web_transcript"},
            episode={"title": "Source Type Fallback"},
        ),
        "doc_4": _build_transcript("doc_4"),
    }
    claims = [
        _build_claim("clm_1", "doc_1"),
        _build_claim("clm_2", "doc_2"),
        _build_claim("clm_3", "doc_2"),
        _build_claim("clm_4", "doc_4"),
    ]
    queries = [
        _build_query("clm_1", "Query 1"),
        _build_query("clm_2", "Query 2"),
        _build_query("clm_3", "Query 3"),
        _build_query("clm_999", "Orphan"),
    ]

    groups, options_by_doc = build_source_episode_index(transcripts, claims, queries)

    alpha_group = next(group for group in groups if group.source_key == "alpha.fm")
    assert alpha_group.episode_doc_ids == ("doc_2", "doc_1")

    assert options_by_doc["doc_2"].episode_title == "Alpha Episode"
    assert options_by_doc["doc_2"].claim_count == 2
    assert options_by_doc["doc_2"].query_count == 2
    assert any(group.source_key == "web_transcript" for group in groups)
    assert any(group.source_key == "unknown_source" for group in groups)


def test_build_segment_to_claims_index_uses_doc_and_seg_id_keys() -> None:
    claims = [
        _build_claim("clm_1", "doc_1", evidence_seg_ids=["seg_000001"]),
        _build_claim("clm_2", "doc_2", evidence_seg_ids=["seg_000001"]),
        _build_claim("clm_3", "doc_1", evidence_seg_ids=["seg_000001", "seg_000002"]),
    ]

    index = build_segment_to_claims_index(claims)

    assert [row.claim_id for row in index[("doc_1", "seg_000001")]] == ["clm_1", "clm_3"]
    assert [row.claim_id for row in index[("doc_2", "seg_000001")]] == ["clm_2"]
    assert [row.claim_id for row in index[("doc_1", "seg_000002")]] == ["clm_3"]


def test_filter_episode_claim_rows_filters_by_speaker_type_and_query_presence() -> None:
    claims = [
        _build_claim("clm_1", "doc_1", speaker="Host", claim_type="medical_risk"),
        _build_claim("clm_2", "doc_1", speaker="Guest", claim_type="nutrition_claim"),
        _build_claim("clm_3", "doc_1", speaker="Host", claim_type="nutrition_claim"),
    ]
    queries_by_claim_id = build_claims_to_queries_index([_build_query("clm_3", "Query 3")])
    rows = build_episode_claim_rows("doc_1", claims, queries_by_claim_id)

    filtered = filter_episode_claim_rows(
        rows,
        selected_speakers=["Host"],
        selected_claim_types=["nutrition_claim"],
        only_with_queries=True,
        search_text="clm_3",
    )

    assert [row.claim_id for row in filtered] == ["clm_3"]


def test_default_claim_for_segment_uses_boldness_then_claim_id() -> None:
    claims = [
        _build_claim("clm_2", "doc_1", boldness_rating=3),
        _build_claim("clm_1", "doc_1", boldness_rating=3),
        _build_claim("clm_3", "doc_1", boldness_rating=2),
    ]

    selected = default_claim_for_segment(claims)

    assert selected is not None
    assert selected.claim_id == "clm_1"


def test_build_source_summary_counts_and_top_speakers() -> None:
    claims = [
        _build_claim("clm_1", "doc_1", speaker="Alice"),
        _build_claim("clm_2", "doc_1", speaker="Bob"),
        _build_claim("clm_3", "doc_2", speaker="Alice"),
        _build_claim("clm_4", "doc_2", speaker="Carol"),
        _build_claim("clm_5", "doc_3", speaker="Ignored"),
    ]
    queries_by_claim_id = build_claims_to_queries_index(
        [
            _build_query("clm_1", "Query 1"),
            _build_query("clm_3", "Query 3"),
            _build_query("clm_4", "Query 4"),
            _build_query("clm_5", "Query 5"),
        ]
    )

    summary = build_source_summary(("doc_1", "doc_2"), claims, queries_by_claim_id)

    assert summary.episode_count == 2
    assert summary.claim_count == 4
    assert summary.query_count == 3
    assert summary.top_speakers == ("Alice", "Bob", "Carol")
