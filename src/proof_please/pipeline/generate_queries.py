"""Validation-query generation stage from extracted claims."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from proof_please.core.io import extract_json_object
from proof_please.core.model_client import chat_with_model
from proof_please.pipeline.chunking import build_chunks
from proof_please.pipeline.dedupe import dedupe_queries
from proof_please.pipeline.models import ModelBackendConfig
from proof_please.pipeline.normalize import generate_heuristic_queries, normalize_query_rows


def build_claims_block(claims: list[dict[str, Any]]) -> str:
    """Render claim rows for query-generation prompt."""
    lines: list[str] = []
    for claim in claims:
        claim_id = str(claim.get("claim_id", "")).strip()
        claim_type = str(claim.get("claim_type", "")).strip()
        claim_text = re.sub(r"\s+", " ", str(claim.get("claim_text", "")).strip())
        if not claim_id or not claim_text:
            continue
        lines.append(f"{claim_id} | {claim_type} | {claim_text}")
    return "\n".join(lines)


def build_query_prompt(claims_block: str, chunk_label: str) -> list[dict[str, str]]:
    """Prompt to generate literature-search queries for validating claims."""
    system = (
        "You generate literature-search queries to validate health claims. "
        "Every `query` must be a single, natural-sounding question that helps evaluate "
        "scientific consensus for a claim or a small set of similar claims. "
        "Return JSON only with this shape: "
        '{"queries":[{"claim_id":"clm_000001","query":"...","why_this_query":"...",' 
        '"preferred_sources":["systematic review","meta-analysis","guideline"]}]}. '
    )
    user = (
        f"Chunk: {chunk_label}\n\n"
        "Task:\n"
        "1) Given the claims below, generate as many high-value validation queries as possible.\n"
        "2) You may merge very similar claims into one query and use one representative claim_id.\n"
        "3) Phrase each query naturally and directly as a question that a human would type in search.\n"
        '   Good: "Is LDL cholesterol an independent risk factor for heart disease?"\n'
        '   Good: "Does reducing saturated fat lower LDL cholesterol?"\n'
        '   Bad: "What is the current scientific consensus on whether LDL cholesterol is an '
        'independent risk factor for heart disease?"\n'
        "4) Keep queries concise and optimized for evidence retrieval.\n"
        '5) Do not use repetitive scaffolding such as "What is the current scientific consensus on...".\n'
        "6) Prefer question openings like Is/Are/Does/Do/Can/Should/How much.\n"
        "7) Do not append source types inside `query`; keep source types only in "
        "`preferred_sources`.\n"
        "8) Prefer source types like systematic review, meta-analysis, guideline, "
        "mendelian randomisation, RCT.\n"
        "9) Return JSON only.\n\n"
        "Claims:\n"
        f"{claims_block}\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def choose_query_model(
    query_model: str | None,
    model_list: list[str],
    available_models: list[str],
) -> str | None:
    """Resolve which model to use for query generation."""
    if query_model:
        return query_model
    for model in model_list:
        if model in available_models:
            return model
    if available_models:
        return available_models[0]
    return None


def generate_validation_queries(
    claims: list[dict[str, Any]],
    config: ModelBackendConfig,
    query_model: str,
    chunk_size: int,
    chunk_overlap: int,
    on_status: Callable[[str], None] | None = None,
    run_id: str = "",
) -> list[dict[str, Any]]:
    """Generate deduplicated validation queries from extracted claims."""

    def emit(message: str) -> None:
        if on_status:
            on_status(message)

    valid_claim_ids = {
        str(claim.get("claim_id", "")).strip()
        for claim in claims
        if str(claim.get("claim_id", "")).strip()
    }
    if not valid_claim_ids:
        return []

    chunks = build_chunks(claims, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    claim_rows_by_id = {
        str(claim.get("claim_id", "")).strip(): claim
        for claim in claims
        if str(claim.get("claim_id", "")).strip()
    }
    query_rows_raw: list[dict[str, Any]] = []

    for chunk_index, chunk in enumerate(chunks, start=1):
        claims_block = build_claims_block(chunk)
        if not claims_block:
            continue
        messages = build_query_prompt(claims_block, chunk_label=f"{chunk_index}/{len(chunks)}")
        try:
            response_text = chat_with_model(config=config, model=query_model, messages=messages)
        except Exception as exc:  # noqa: BLE001 - prototype tolerance
            emit(f"Query generation failed for chunk {chunk_index}/{len(chunks)}: {exc}")
            continue

        try:
            payload = extract_json_object(response_text)
        except ValueError as exc:
            emit(f"Invalid query JSON for chunk {chunk_index}/{len(chunks)}: {exc}")
            continue

        raw_queries = payload.get("queries", [])
        if not isinstance(raw_queries, list):
            continue
        normalized = normalize_query_rows(
            raw_queries,
            valid_claim_ids=valid_claim_ids,
            run_id=run_id,
            claim_rows_by_id=claim_rows_by_id,
        )
        query_rows_raw.extend(normalized)
        emit(f"{query_model} query chunk {chunk_index}/{len(chunks)}: {len(normalized)} queries")

    deduped_llm_queries = dedupe_queries(query_rows_raw)
    covered_claim_ids = {row["claim_id"] for row in deduped_llm_queries}
    missing_claims = [
        claim
        for claim in claims
        if str(claim.get("claim_id", "")).strip()
        and str(claim.get("claim_id", "")).strip() not in covered_claim_ids
    ]
    if missing_claims:
        emit(f"Adding fallback queries for {len(missing_claims)} uncovered claims.")
        deduped_llm_queries.extend(generate_heuristic_queries(missing_claims, run_id=run_id))

    return dedupe_queries(deduped_llm_queries)
