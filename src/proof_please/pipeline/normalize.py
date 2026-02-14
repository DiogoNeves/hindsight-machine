"""Normalization helpers for extracted claims and generated queries."""

from __future__ import annotations

import re
from typing import Any

from proof_please.pipeline.models import (
    ALLOWED_CLAIM_TYPES,
    ClaimRecord,
    EvidenceItem,
    EvidenceSpan,
    QueryRecord,
    TimeRange,
)


def normalize_evidence(evidence: Any) -> list[dict[str, str]]:
    """Normalize evidence payload into seg_id/quote rows."""
    if not isinstance(evidence, list):
        return []
    output: list[dict[str, str]] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        try:
            normalized = EvidenceItem.model_validate(item)
        except Exception:  # noqa: BLE001 - preserve lenient prototype behavior
            continue
        if normalized.seg_id and normalized.quote:
            output.append(normalized.model_dump())
    return output


def derive_time_range(
    claim: dict[str, Any],
    fallback_start: int = 0,
    fallback_end: int | None = None,
) -> dict[str, int]:
    """Build robust claim time range from payload and fallbacks."""
    if fallback_end is None:
        fallback_end = fallback_start
    time_range = claim.get("time_range_s", {})
    if isinstance(time_range, dict):
        start = time_range.get("start", fallback_start)
        end = time_range.get("end", fallback_end)
    else:
        start = fallback_start
        end = fallback_end

    normalized = TimeRange.model_validate({"start": start, "end": end})
    return normalized.model_dump()


def normalize_boldness_rating(claim: dict[str, Any]) -> int:
    """Normalize boldness/surprise score into a 1-3 int."""
    raw_value = claim.get("boldness_rating", claim.get("surprise_rating", 2))
    return ClaimRecord.model_validate(
        {
            "doc_id": "",
            "speaker": "",
            "claim_text": "placeholder",
            "evidence": [{"seg_id": "seg", "quote": "quote"}],
            "time_range_s": {"start": 0, "end": 0},
            "claim_type": "other",
            "boldness_rating": raw_value,
            "model": "",
            "provenance": {
                "run_id": "run_placeholder",
                "step": "extract_claims",
                "input_refs": [],
                "evidence_span": {},
                "rationale": "placeholder",
            },
        }
    ).boldness_rating


def normalize_claims(
    doc_id: str,
    model: str,
    raw_claims: list[dict[str, Any]],
    start_time_by_seg_id: dict[str, int],
    run_id: str,
) -> list[dict[str, Any]]:
    """Normalize model output into final JSONL rows."""
    out: list[dict[str, Any]] = []
    for claim in raw_claims:
        if not isinstance(claim, dict):
            continue
        speaker = str(claim.get("speaker", "")).strip()
        claim_text = str(claim.get("claim_text", "")).strip()
        evidence = normalize_evidence(claim.get("evidence"))
        if not claim_text or not evidence:
            continue
        evidence_starts = [
            start_time_by_seg_id[ev["seg_id"]]
            for ev in evidence
            if ev["seg_id"] in start_time_by_seg_id
        ]
        fallback_start = min(evidence_starts) if evidence_starts else 0
        fallback_end = max(evidence_starts) if evidence_starts else fallback_start
        claim_type = str(claim.get("claim_type", "other")).strip() or "other"
        if claim_type not in ALLOWED_CLAIM_TYPES:
            claim_type = "other"
        boldness_rating = normalize_boldness_rating(claim)
        time_range = derive_time_range(
            claim,
            fallback_start=fallback_start,
            fallback_end=fallback_end,
        )
        try:
            segment_ids = [item["seg_id"] for item in evidence]
            evidence_span = EvidenceSpan.model_validate(
                {
                    "segment_ids": segment_ids,
                    "time_range_s": time_range,
                }
            )
            normalized = ClaimRecord.model_validate(
                {
                    "doc_id": doc_id,
                    "speaker": speaker,
                    "claim_text": claim_text,
                    "evidence": evidence,
                    "time_range_s": time_range,
                    "claim_type": claim_type,
                    "boldness_rating": boldness_rating,
                    "model": model,
                    "provenance": {
                        "run_id": run_id,
                        "step": "extract_claims",
                        "input_refs": segment_ids,
                        "evidence_span": evidence_span.model_dump(),
                        "rationale": (
                            f"Extracted from transcript evidence spans by model {model}."
                        ),
                    },
                }
            )
        except Exception:  # noqa: BLE001 - preserve lenient prototype behavior
            continue
        out.append(normalized.model_dump(exclude_none=True))
    return out


def naturalize_query_question(text: str) -> str:
    """Convert repetitive consensus phrasing into short natural questions."""
    query = re.sub(r"\s+", " ", text.strip())
    if not query:
        return ""

    patterns = [
        r"(?i)^what is the current scientific consensus on whether (.+)\??$",
        r"(?i)^what is the current scientific consensus on the claim that (.+)\??$",
        r"(?i)^what is the current scientific consensus on (.+)\??$",
    ]
    for pattern in patterns:
        match = re.match(pattern, query)
        if match:
            query = match.group(1).strip()
            break

    query = query.rstrip(" .")
    if not query:
        return ""
    if query.endswith("?"):
        return query

    if re.match(
        r"(?i)^(is|are|can|could|should|would|do|does|did|has|have|had|will|was|were)\b",
        query,
    ):
        return f"{query}?"

    match = re.match(r"(?i)^(.+?)\s+is\s+(.+)$", query)
    if match:
        return f"Is {match.group(1).strip()} {match.group(2).strip()}?"
    match = re.match(r"(?i)^(.+?)\s+are\s+(.+)$", query)
    if match:
        return f"Are {match.group(1).strip()} {match.group(2).strip()}?"
    match = re.match(r"(?i)^(.+?)\s+can\s+(.+)$", query)
    if match:
        return f"Can {match.group(1).strip()} {match.group(2).strip()}?"
    match = re.match(r"(?i)^(.+?)\s+does\s+not\s+(.+)$", query)
    if match:
        return f"Does {match.group(1).strip()} not {match.group(2).strip()}?"
    match = re.match(r"(?i)^(.+?)\s+do\s+not\s+(.+)$", query)
    if match:
        return f"Do {match.group(1).strip()} not {match.group(2).strip()}?"

    return f"Is it true that {query}?"


def normalize_query_rows(
    raw_queries: list[dict[str, Any]],
    valid_claim_ids: set[str],
    run_id: str,
    claim_rows_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Normalize model query rows into the expected JSONL schema."""
    rows: list[dict[str, Any]] = []
    for row in raw_queries:
        if not isinstance(row, dict):
            continue
        claim_id = str(row.get("claim_id", "")).strip()
        query = re.sub(r"\s+", " ", str(row.get("query", "")).strip())
        why_this_query = re.sub(r"\s+", " ", str(row.get("why_this_query", "")).strip())
        preferred_sources = row.get("preferred_sources", [])
        query = naturalize_query_question(query)
        if claim_id not in valid_claim_ids:
            continue
        if not query or not why_this_query:
            continue
        if not isinstance(preferred_sources, list):
            preferred_sources = []
        normalized_sources = [
            re.sub(r"\s+", " ", str(item).strip())
            for item in preferred_sources
            if str(item).strip()
        ]
        if not normalized_sources:
            normalized_sources = ["systematic review", "meta-analysis", "guideline"]
        try:
            claim_row = claim_rows_by_id.get(claim_id, {})
            claim_provenance = claim_row.get("provenance", {}) if isinstance(claim_row, dict) else {}
            evidence_span = claim_provenance.get("evidence_span", {})
            normalized = QueryRecord.model_validate(
                {
                    "claim_id": claim_id,
                    "query": query,
                    "why_this_query": why_this_query,
                    "preferred_sources": normalized_sources,
                    "provenance": {
                        "run_id": run_id,
                        "step": "generate_queries",
                        "input_refs": [claim_id],
                        "evidence_span": evidence_span if isinstance(evidence_span, dict) else {},
                        "rationale": why_this_query,
                    },
                }
            )
        except Exception:  # noqa: BLE001 - preserve lenient prototype behavior
            continue
        rows.append(normalized.model_dump())
    return rows


def sources_for_claim_type(claim_type: str) -> list[str]:
    """Pick source preferences by claim type."""
    if claim_type == "medical_risk":
        return ["systematic review", "meta-analysis", "guideline", "mendelian randomisation"]
    if claim_type == "treatment_effect":
        return ["systematic review", "meta-analysis", "RCT", "guideline"]
    if claim_type == "nutrition_claim":
        return ["systematic review", "meta-analysis", "RCT", "guideline"]
    if claim_type == "exercise_claim":
        return ["systematic review", "meta-analysis", "RCT", "guideline"]
    if claim_type == "epidemiology":
        return ["systematic review", "meta-analysis", "cohort study", "guideline"]
    return ["systematic review", "meta-analysis", "guideline"]


def clean_query_terms(claim_text: str, max_terms: int = 12) -> str:
    """Reduce claim text to key query tokens."""
    stop = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "to",
        "of",
        "and",
        "or",
        "in",
        "for",
        "on",
        "with",
        "that",
        "this",
        "it",
        "as",
        "by",
        "be",
        "from",
        "at",
        "about",
        "can",
        "could",
    }
    tokens = re.findall(r"[a-zA-Z0-9%\-]+", claim_text.lower())
    filtered = [tok for tok in tokens if tok not in stop]
    if not filtered:
        filtered = tokens
    return " ".join(filtered[:max_terms])


def _claim_tokens(claim_text: str, max_terms: int = 14) -> set[str]:
    cleaned = clean_query_terms(claim_text, max_terms=max_terms)
    return {tok for tok in cleaned.split() if tok}


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def generate_heuristic_queries(claims: list[dict[str, Any]], run_id: str) -> list[dict[str, Any]]:
    """Fallback query generation for claims not covered by LLM output."""
    rows: list[dict[str, Any]] = []
    existing_token_groups: list[set[str]] = []
    for claim in claims:
        claim_id = str(claim.get("claim_id", "")).strip()
        claim_text = str(claim.get("claim_text", "")).strip()
        claim_type = str(claim.get("claim_type", "other")).strip() or "other"
        if not claim_id or not claim_text:
            continue
        tokens = _claim_tokens(claim_text)
        if any(_jaccard_similarity(tokens, group) >= 0.72 for group in existing_token_groups):
            continue
        existing_token_groups.append(tokens)
        source_types = sources_for_claim_type(claim_type)
        query = naturalize_query_question(claim_text)
        try:
            claim_provenance = claim.get("provenance", {}) if isinstance(claim, dict) else {}
            evidence_span = claim_provenance.get("evidence_span", {})
            rationale = (
                "Fallback query for claim validation using high-evidence source types "
                "matched to claim category."
            )
            normalized = QueryRecord.model_validate(
                {
                    "claim_id": claim_id,
                    "query": query,
                    "why_this_query": rationale,
                    "preferred_sources": source_types,
                    "provenance": {
                        "run_id": run_id,
                        "step": "generate_queries",
                        "input_refs": [claim_id],
                        "evidence_span": evidence_span if isinstance(evidence_span, dict) else {},
                        "rationale": rationale,
                    },
                }
            )
        except Exception:  # noqa: BLE001 - preserve lenient prototype behavior
            continue
        rows.append(normalized.model_dump())
    return rows
