"""Claim extraction stage for normalized transcripts."""

from __future__ import annotations

import re
import urllib.error
from collections.abc import Callable
from typing import Any

from proof_please.core.io import extract_json_object
from proof_please.core.model_client import chat_with_model
from proof_please.pipeline.chunking import build_chunks
from proof_please.pipeline.dedupe import dedupe_and_assign_claim_ids
from proof_please.pipeline.models import ModelBackendConfig
from proof_please.pipeline.normalize import normalize_claims


def build_segment_block(segments: list[dict[str, Any]], max_segments: int) -> str:
    """Render transcript segments as compact lines for the LLM prompt."""
    lines: list[str] = []
    for segment in segments[:max_segments]:
        seg_id = str(segment.get("seg_id", "")).strip()
        speaker = str(segment.get("speaker", "")).strip()
        start = int(segment.get("start_time_s", 0))
        text = re.sub(r"\s+", " ", str(segment.get("text", "")).strip())
        if not seg_id or not text:
            continue
        lines.append(f"{seg_id} | {start} | {speaker} | {text}")
    return "\n".join(lines)


def build_prompt(doc_id: str, segment_block: str, chunk_label: str) -> list[dict[str, str]]:
    """Build strict JSON extraction prompt."""
    system = (
        "You extract health and medical claims from transcripts. "
        "Return JSON only with this shape: "
        '{"claims":[{"speaker":"...","claim_text":"...","evidence":[{"seg_id":"...","quote":"..."}],' 
        '"time_range_s":{"start":0,"end":0},"claim_type":"medical_risk","boldness_rating":2}]}. '
        "Do not add markdown or commentary."
    )
    user = (
        f"Document ID: {doc_id}\n\n"
        f"Chunk: {chunk_label}\n\n"
        "Task:\n"
        "1) Extract as many distinct health claims as possible from the transcript snippets below.\n"
        "2) A claim must be either:\n"
        "   - factual health/medical information presented as generally true, or\n"
        "   - advice/recommendation intended to change listener behavior.\n"
        "3) Exclude purely personal anecdotes about the speaker's own experience unless they are clearly "
        "generalized to others or used as advice.\n"
        "4) Use claim_type from this set only: medical_risk, treatment_effect, nutrition_claim, "
        "exercise_claim, epidemiology, other.\n"
        "5) Each claim must include at least one evidence item with an exact seg_id and quote.\n"
        "6) time_range_s.start and end must be integer seconds; derive from evidence segment starts.\n"
        "7) Add boldness_rating on a 1-3 scale for how bold/surprising the claim is:\n"
        "   1 = common/unsurprising mainstream statement\n"
        "   2 = moderately strong or somewhat surprising statement\n"
        "   3 = very bold, counter-intuitive, or highly surprising statement\n"
        "8) Prefer recall over precision: include explicit claims about risk, causality, effects, "
        "recommendations, prevalence, biomarkers, or dose-response.\n\n"
        "Transcript segments:\n"
        f"{segment_block}\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def extract_claims_for_models(
    doc_id: str,
    segments: list[dict[str, Any]],
    model_list: list[str],
    config: ModelBackendConfig,
    chunk_size: int,
    chunk_overlap: int,
    on_status: Callable[[str], None] | None = None,
    run_id: str = "",
) -> list[dict[str, Any]]:
    """Run multi-model claim extraction and return deduplicated rows."""

    def emit(message: str) -> None:
        if on_status:
            on_status(message)

    chunks = build_chunks(segments, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    start_time_by_seg_id = {
        str(segment.get("seg_id", "")).strip(): int(segment.get("start_time_s", 0))
        for segment in segments
        if str(segment.get("seg_id", "")).strip()
    }

    all_rows_raw: list[dict[str, Any]] = []
    for model in model_list:
        emit(f"Running extraction with model: {model}")
        model_rows: list[dict[str, Any]] = []
        for chunk_index, chunk in enumerate(chunks, start=1):
            segment_block = build_segment_block(chunk, max_segments=len(chunk))
            messages = build_prompt(
                doc_id,
                segment_block,
                chunk_label=f"{chunk_index}/{len(chunks)}",
            )
            try:
                response_text = chat_with_model(config=config, model=model, messages=messages)
            except urllib.error.URLError as exc:
                emit(f"Failed request for model {model}, chunk {chunk_index}: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001 - keep prototype error handling simple
                emit(f"Model {model}, chunk {chunk_index} failed: {exc}")
                continue

            try:
                payload = extract_json_object(response_text)
            except ValueError as exc:
                snippet = response_text[:240].replace("\n", " ")
                emit(
                    "Could not parse JSON response for "
                    f"{model}, chunk {chunk_index}: {exc} (snippet: {snippet!r})"
                )
                continue

            claims = payload.get("claims", [])
            if not isinstance(claims, list):
                emit(f"Model {model}, chunk {chunk_index} returned no claims list.")
                continue

            normalized_rows = normalize_claims(
                doc_id=doc_id,
                model=model,
                raw_claims=claims,
                start_time_by_seg_id=start_time_by_seg_id,
                run_id=run_id,
            )
            model_rows.extend(normalized_rows)
            emit(f"{model} chunk {chunk_index}/{len(chunks)}: {len(normalized_rows)} claims")

        deduped_model_rows = dedupe_and_assign_claim_ids(model_rows)
        all_rows_raw.extend(deduped_model_rows)
        emit(
            f"Model {model} produced {len(deduped_model_rows)} unique claims "
            f"across {len(chunks)} chunks."
        )

    return dedupe_and_assign_claim_ids(all_rows_raw)
