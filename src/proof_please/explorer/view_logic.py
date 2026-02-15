"""Pure helper logic for explorer view filtering and labeling."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from urllib.parse import urlparse

from proof_please.explorer.models import ClaimRow, QueryRow
from proof_please.pipeline.models import TranscriptDocument

PREVIEW_LIMIT = 96
SegmentKey = tuple[str, str]


@dataclass(frozen=True)
class EpisodeOption:
    """Display metadata for episode selection controls."""

    doc_id: str
    source_key: str
    source_label: str
    episode_title: str
    published_date: str
    claim_count: int
    query_count: int


@dataclass(frozen=True)
class SourceGroup:
    """Episodes grouped under a source key."""

    source_key: str
    source_label: str
    episode_doc_ids: tuple[str, ...]


@dataclass(frozen=True)
class EpisodeClaimRow:
    """Compact claim row rendered in episode-first controls."""

    claim_id: str
    doc_id: str
    speaker: str
    claim_type: str
    claim_text: str
    boldness_rating: int | None
    query_count: int
    first_seg_id: str


@dataclass(frozen=True)
class SourceSummary:
    """High-level source summary shown in the episode browser."""

    episode_count: int
    claim_count: int
    query_count: int
    top_speakers: tuple[str, ...]


def _normalize_text(value: object) -> str:
    return str(value or "").strip()


def _source_key_for_document(document: TranscriptDocument) -> str:
    source = document.source if isinstance(document.source, dict) else {}
    source_url = _normalize_text(source.get("url", ""))
    if source_url:
        parsed = urlparse(source_url)
        host = parsed.netloc.lower().strip()
        if host.startswith("www."):
            host = host[4:]
        if host:
            return host

    source_type = _normalize_text(source.get("type", "")).lower()
    if source_type:
        return source_type
    return "unknown_source"


def _episode_title_for_document(document: TranscriptDocument) -> str:
    episode = document.episode if isinstance(document.episode, dict) else {}
    title = _normalize_text(episode.get("title", ""))
    return title or document.doc_id


def _published_date_for_document(document: TranscriptDocument) -> str:
    episode = document.episode if isinstance(document.episode, dict) else {}
    return _normalize_text(episode.get("published_date", ""))


def episode_option_label(option: EpisodeOption) -> str:
    """Build a compact label for an episode option."""
    date_prefix = f"{option.published_date} - " if option.published_date else ""
    return (
        f"{date_prefix}{option.episode_title} "
        f"({option.claim_count} claims, {option.query_count} queries)"
    )


def build_claims_to_queries_index(queries: list[QueryRow]) -> dict[str, list[QueryRow]]:
    """Group query rows by claim_id."""
    grouped: dict[str, list[QueryRow]] = defaultdict(list)
    for query in queries:
        grouped[query.claim_id].append(query)
    return dict(grouped)


def build_segment_to_claims_index(claims: list[ClaimRow]) -> dict[SegmentKey, list[ClaimRow]]:
    """Index claims by (doc_id, seg_id) evidence references."""
    index: dict[SegmentKey, list[ClaimRow]] = defaultdict(list)
    for claim in claims:
        for evidence in claim.evidence:
            seg_id = _normalize_text(evidence.seg_id)
            if not seg_id:
                continue
            index[(claim.doc_id, seg_id)].append(claim)

    return {
        key: sorted(rows, key=lambda row: row.claim_id)
        for key, rows in index.items()
    }


def build_source_episode_index(
    transcripts_by_doc_id: dict[str, TranscriptDocument],
    claims: list[ClaimRow],
    queries: list[QueryRow],
) -> tuple[list[SourceGroup], dict[str, EpisodeOption]]:
    """Build deterministic source and episode structures for the browser UI."""
    claims_by_doc_id: dict[str, list[ClaimRow]] = defaultdict(list)
    for claim in claims:
        claims_by_doc_id[claim.doc_id].append(claim)

    queries_by_claim_id = build_claims_to_queries_index(queries)

    episodes_by_doc_id: dict[str, EpisodeOption] = {}
    source_to_doc_ids: dict[str, list[str]] = defaultdict(list)
    for doc_id, document in sorted(transcripts_by_doc_id.items()):
        source_key = _source_key_for_document(document)
        source_to_doc_ids[source_key].append(doc_id)

        doc_claims = claims_by_doc_id.get(doc_id, [])
        query_count = sum(len(queries_by_claim_id.get(row.claim_id, [])) for row in doc_claims)
        episodes_by_doc_id[doc_id] = EpisodeOption(
            doc_id=doc_id,
            source_key=source_key,
            source_label=source_key,
            episode_title=_episode_title_for_document(document),
            published_date=_published_date_for_document(document),
            claim_count=len(doc_claims),
            query_count=query_count,
        )

    source_groups: list[SourceGroup] = []
    for source_key, doc_ids in source_to_doc_ids.items():
        sorted_doc_ids = tuple(
            sorted(
                doc_ids,
                key=lambda doc_id: (
                    episodes_by_doc_id[doc_id].episode_title.lower(),
                    doc_id.lower(),
                ),
            )
        )
        source_groups.append(
            SourceGroup(
                source_key=source_key,
                source_label=source_key,
                episode_doc_ids=sorted_doc_ids,
            )
        )

    source_groups.sort(key=lambda row: (row.source_label.lower(), row.source_key.lower()))
    return source_groups, episodes_by_doc_id


def build_episode_claim_rows(
    doc_id: str,
    claims: list[ClaimRow],
    queries_by_claim_id: dict[str, list[QueryRow]],
) -> list[EpisodeClaimRow]:
    """Build compact claim rows for a selected episode."""
    episode_claims = sorted(
        [row for row in claims if row.doc_id == doc_id],
        key=lambda row: row.claim_id,
    )
    rows: list[EpisodeClaimRow] = []
    for claim in episode_claims:
        first_seg_id = claim.evidence[0].seg_id if claim.evidence else ""
        rows.append(
            EpisodeClaimRow(
                claim_id=claim.claim_id,
                doc_id=claim.doc_id,
                speaker=claim.speaker,
                claim_type=claim.claim_type,
                claim_text=claim.claim_text,
                boldness_rating=claim.boldness_rating,
                query_count=len(queries_by_claim_id.get(claim.claim_id, [])),
                first_seg_id=first_seg_id,
            )
        )
    return rows


def filter_episode_claim_rows(
    rows: list[EpisodeClaimRow],
    *,
    selected_speakers: list[str],
    selected_claim_types: list[str],
    only_with_queries: bool,
    search_text: str,
) -> list[EpisodeClaimRow]:
    """Filter episode claim rows based on browser controls."""
    normalized_search = search_text.strip().lower()
    filtered: list[EpisodeClaimRow] = []
    for row in rows:
        if selected_speakers and row.speaker not in selected_speakers:
            continue
        if selected_claim_types and row.claim_type not in selected_claim_types:
            continue
        if only_with_queries and row.query_count == 0:
            continue
        if normalized_search:
            haystack = " ".join(
                [row.claim_id, row.speaker, row.claim_type, row.claim_text]
            ).lower()
            if normalized_search not in haystack:
                continue
        filtered.append(row)
    return filtered


def default_claim_for_segment(claims: list[ClaimRow]) -> ClaimRow | None:
    """Choose a deterministic default claim for a selected segment."""
    if not claims:
        return None
    ranked = sorted(
        claims,
        key=lambda row: (-(row.boldness_rating or 0), row.claim_id),
    )
    return ranked[0]


def build_source_summary(
    source_doc_ids: tuple[str, ...],
    claims: list[ClaimRow],
    queries_by_claim_id: dict[str, list[QueryRow]],
) -> SourceSummary:
    """Build a compact source-level summary for selected source group."""
    source_doc_id_set = set(source_doc_ids)
    source_claims = [row for row in claims if row.doc_id in source_doc_id_set]
    query_count = sum(len(queries_by_claim_id.get(row.claim_id, [])) for row in source_claims)

    speaker_counts = Counter(row.speaker for row in source_claims if row.speaker)
    ranked_speakers = sorted(speaker_counts.items(), key=lambda row: (-row[1], row[0].lower()))
    top_speakers = tuple(name for name, _ in ranked_speakers[:3])

    return SourceSummary(
        episode_count=len(source_doc_ids),
        claim_count=len(source_claims),
        query_count=query_count,
        top_speakers=top_speakers,
    )


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
