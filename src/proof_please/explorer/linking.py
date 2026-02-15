"""Pure linking logic for claims, queries, and transcript segments."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from proof_please.explorer.models import ClaimRow, QueryRow
from proof_please.pipeline.models import TranscriptDocument, TranscriptSegment


@dataclass(frozen=True)
class ResolvedEvidence:
    """Evidence item resolved to a transcript segment (or marked missing)."""

    claim_id: str
    doc_id: str
    seg_id: str
    quote: str
    found: bool
    speaker: str = ""
    start_time_s: int = 0
    segment_text: str = ""


@dataclass(frozen=True)
class LinkDiagnostics:
    """Cross-artifact linkage health report."""

    total_claims: int
    total_queries: int
    total_transcript_docs: int
    orphan_queries: list[QueryRow]
    claims_without_queries: list[ClaimRow]
    claims_missing_transcript_doc: list[ClaimRow]
    claims_without_evidence: list[ClaimRow]
    missing_evidence_links: list[ResolvedEvidence]


def index_claims_by_id(claims: list[ClaimRow]) -> dict[str, ClaimRow]:
    """Index claim rows by claim_id, keeping first occurrence for duplicates."""
    index: dict[str, ClaimRow] = {}
    for claim in claims:
        if claim.claim_id in index:
            continue
        index[claim.claim_id] = claim
    return index


def group_queries_by_claim_id(queries: list[QueryRow]) -> dict[str, list[QueryRow]]:
    """Group query rows by linked claim_id."""
    grouped: dict[str, list[QueryRow]] = defaultdict(list)
    for query in queries:
        grouped[query.claim_id].append(query)
    return dict(grouped)


def _segment_index_for_document(document: TranscriptDocument) -> dict[str, TranscriptSegment]:
    index: dict[str, TranscriptSegment] = {}
    for segment in document.segments:
        if not segment.seg_id:
            continue
        if segment.seg_id in index:
            continue
        index[segment.seg_id] = segment
    return index


def resolve_claim_evidence(
    claim: ClaimRow,
    transcripts_by_doc_id: dict[str, TranscriptDocument],
) -> list[ResolvedEvidence]:
    """Resolve claim evidence rows into transcript segments when available."""
    document = transcripts_by_doc_id.get(claim.doc_id)
    if document is None:
        return [
            ResolvedEvidence(
                claim_id=claim.claim_id,
                doc_id=claim.doc_id,
                seg_id=evidence.seg_id,
                quote=evidence.quote,
                found=False,
            )
            for evidence in claim.evidence
        ]

    segment_index = _segment_index_for_document(document)
    resolved_rows: list[ResolvedEvidence] = []
    for evidence in claim.evidence:
        segment = segment_index.get(evidence.seg_id)
        if segment is None:
            resolved_rows.append(
                ResolvedEvidence(
                    claim_id=claim.claim_id,
                    doc_id=claim.doc_id,
                    seg_id=evidence.seg_id,
                    quote=evidence.quote,
                    found=False,
                )
            )
            continue

        resolved_rows.append(
            ResolvedEvidence(
                claim_id=claim.claim_id,
                doc_id=claim.doc_id,
                seg_id=evidence.seg_id,
                quote=evidence.quote,
                found=True,
                speaker=segment.speaker,
                start_time_s=segment.start_time_s,
                segment_text=segment.text,
            )
        )
    return resolved_rows


def compute_link_diagnostics(
    claims: list[ClaimRow],
    queries: list[QueryRow],
    transcripts_by_doc_id: dict[str, TranscriptDocument],
) -> LinkDiagnostics:
    """Compute data-link diagnostics across claim/query/transcript artifacts."""
    claim_index = index_claims_by_id(claims)
    queries_by_claim_id = group_queries_by_claim_id(queries)

    orphan_queries = [query for query in queries if query.claim_id not in claim_index]
    claims_without_queries = [claim for claim in claims if claim.claim_id not in queries_by_claim_id]
    claims_missing_transcript_doc = [
        claim for claim in claims if claim.doc_id not in transcripts_by_doc_id
    ]
    claims_without_evidence = [claim for claim in claims if not claim.evidence]

    missing_evidence_links: list[ResolvedEvidence] = []
    for claim in claims:
        if claim.doc_id not in transcripts_by_doc_id:
            continue
        for resolved in resolve_claim_evidence(claim, transcripts_by_doc_id):
            if not resolved.found:
                missing_evidence_links.append(resolved)

    return LinkDiagnostics(
        total_claims=len(claims),
        total_queries=len(queries),
        total_transcript_docs=len(transcripts_by_doc_id),
        orphan_queries=orphan_queries,
        claims_without_queries=claims_without_queries,
        claims_missing_transcript_doc=claims_missing_transcript_doc,
        claims_without_evidence=claims_without_evidence,
        missing_evidence_links=missing_evidence_links,
    )
