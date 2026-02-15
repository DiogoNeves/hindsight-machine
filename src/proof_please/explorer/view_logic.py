"""Pure helper logic for explorer view filtering and labeling."""

from __future__ import annotations

from proof_please.explorer.models import ClaimRow, QueryRow

PREVIEW_LIMIT = 96


def truncate_preview(text: str, limit: int = PREVIEW_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."


def claim_matches_filters(
    claim: ClaimRow,
    *,
    selected_doc: str,
    selected_speakers: list[str],
    selected_claim_types: list[str],
    selected_models: list[str],
    only_with_queries: bool,
    queries_by_claim_id: dict[str, list[QueryRow]],
    search_text: str,
) -> bool:
    if selected_doc != "All" and claim.doc_id != selected_doc:
        return False
    if selected_speakers and claim.speaker not in selected_speakers:
        return False
    if selected_claim_types and claim.claim_type not in selected_claim_types:
        return False
    if selected_models and claim.model not in selected_models:
        return False
    if only_with_queries and claim.claim_id not in queries_by_claim_id:
        return False
    if not search_text:
        return True

    haystack = " ".join(
        [claim.claim_id, claim.doc_id, claim.speaker, claim.claim_type, claim.claim_text]
    ).lower()
    return search_text in haystack


def query_matches_filters(
    query: QueryRow,
    *,
    linked_claim: ClaimRow | None,
    selected_claim_types: list[str],
    selected_source_set: set[str],
    only_orphans: bool,
    search_text: str,
) -> bool:
    if only_orphans and linked_claim is not None:
        return False
    if selected_claim_types:
        if linked_claim is None or linked_claim.claim_type not in selected_claim_types:
            return False
    if selected_source_set and not selected_source_set.intersection(query.preferred_sources):
        return False
    if not search_text:
        return True

    claim_text = linked_claim.claim_text if linked_claim else ""
    haystack = " ".join([query.query, query.why_this_query, claim_text]).lower()
    return search_text in haystack
