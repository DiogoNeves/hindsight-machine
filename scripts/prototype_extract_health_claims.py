"""Prototype script to extract health claims from a normalized transcript using Ollama."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
from rich.console import Console

console = Console()

DEFAULT_INPUT = Path("data/transcripts/norm/web__the-ready-state__layne-norton__2022-10-20__v1.json")
DEFAULT_OUTPUT = Path("data/claims.jsonl")
DEFAULT_QUERIES_OUTPUT = Path("data/claim_queries.jsonl")
DEFAULT_MODELS = "gpt-oss:20b,qwen3:4b"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"

ALLOWED_CLAIM_TYPES = {
    "medical_risk",
    "treatment_effect",
    "nutrition_claim",
    "exercise_claim",
    "epidemiology",
    "other",
}


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str
    timeout: float


def _endpoint(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*", "", cleaned)
        cleaned = cleaned.replace("```", "")
    decoder = json.JSONDecoder()
    idx = 0
    last_obj: dict[str, Any] | None = None
    while True:
        start = cleaned.find("{", idx)
        if start == -1:
            break
        try:
            obj, end = decoder.raw_decode(cleaned[start:])
            if isinstance(obj, dict):
                last_obj = obj
            idx = start + end
        except json.JSONDecodeError:
            idx = start + 1
    if last_obj is None:
        raise ValueError("No JSON object found in model response.")
    return last_obj


def list_ollama_models(config: OllamaConfig) -> list[str]:
    """Fetch installed model names from Ollama /api/tags."""
    req = urllib.request.Request(
        _endpoint(config.base_url, "/api/tags"),
        headers={"Content-Type": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=config.timeout) as resp:
        data = json.load(resp)
    models = data.get("models", [])
    names: list[str] = []
    for model in models:
        name = model.get("name") or model.get("model")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def ollama_chat(
    config: OllamaConfig,
    model: str,
    messages: list[dict[str, str]],
) -> str:
    """Call Ollama /api/chat and return message content."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "format": "json",
        "options": {
            "temperature": 0.0,
            "num_predict": 1200,
        },
    }
    req = urllib.request.Request(
        _endpoint(config.base_url, "/api/chat"),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=config.timeout) as resp:
        body = json.load(resp)
    message = body.get("message", {})
    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError("Ollama response missing message content.")
    return content


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
        "1) Extract as many distinct factual health claims as possible from the transcript snippets below.\n"
        "2) Use claim_type from this set only: medical_risk, treatment_effect, nutrition_claim, "
        "exercise_claim, epidemiology, other.\n"
        "3) Each claim must include at least one evidence item with an exact seg_id and quote.\n"
        "4) time_range_s.start and end must be integer seconds; derive from evidence segment starts.\n"
        "5) Add boldness_rating on a 1-3 scale for how bold/surprising the claim is:\n"
        "   1 = common/unsurprising mainstream statement\n"
        "   2 = moderately strong or somewhat surprising statement\n"
        "   3 = very bold, counter-intuitive, or highly surprising statement\n"
        "6) Prefer recall over precision: include explicit claims about risk, causality, effects, "
        "recommendations, prevalence, biomarkers, or dose-response.\n\n"
        "Transcript segments:\n"
        f"{segment_block}\n"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _normalize_evidence(evidence: Any) -> list[dict[str, str]]:
    if not isinstance(evidence, list):
        return []
    output: list[dict[str, str]] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        seg_id = str(item.get("seg_id", "")).strip()
        quote = str(item.get("quote", "")).strip()
        if seg_id and quote:
            output.append({"seg_id": seg_id, "quote": quote})
    return output


def _derive_time_range(
    claim: dict[str, Any],
    fallback_start: int = 0,
    fallback_end: int | None = None,
) -> dict[str, int]:
    if fallback_end is None:
        fallback_end = fallback_start
    time_range = claim.get("time_range_s", {})
    if isinstance(time_range, dict):
        start = time_range.get("start", fallback_start)
        end = time_range.get("end", fallback_end)
    else:
        start = fallback_start
        end = fallback_end
    try:
        start_i = int(start)
        end_i = int(end)
    except (TypeError, ValueError):
        start_i = fallback_start
        end_i = fallback_start
    if end_i < start_i:
        end_i = start_i
    return {"start": start_i, "end": end_i}


def _normalize_boldness_rating(claim: dict[str, Any]) -> int:
    raw_value = claim.get("boldness_rating", claim.get("surprise_rating", 2))
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = 2
    if value < 1:
        return 1
    if value > 3:
        return 3
    return value


def build_chunks(
    segments: list[dict[str, Any]],
    chunk_size: int,
    chunk_overlap: int,
) -> list[list[dict[str, Any]]]:
    """Split segments into overlapping chunks."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must be >= 0")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")

    chunks: list[list[dict[str, Any]]] = []
    step = chunk_size - chunk_overlap
    for start in range(0, len(segments), step):
        chunk = segments[start : start + chunk_size]
        if not chunk:
            continue
        chunks.append(chunk)
        if start + chunk_size >= len(segments):
            break
    return chunks


def _claim_dedupe_key(row: dict[str, Any]) -> tuple[str, str, tuple[str, ...]]:
    normalized_text = re.sub(r"\W+", " ", str(row.get("claim_text", "")).lower()).strip()
    evidence = row.get("evidence", [])
    seg_ids = tuple(
        sorted(
            str(item.get("seg_id", "")).strip()
            for item in evidence
            if isinstance(item, dict) and str(item.get("seg_id", "")).strip()
        )
    )
    return (str(row.get("model", "")), normalized_text, seg_ids)


def dedupe_and_assign_claim_ids(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate repeated chunk claims and assign final claim IDs."""
    unique_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for row in rows:
        key = _claim_dedupe_key(row)
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)

    final_rows: list[dict[str, Any]] = []
    for index, row in enumerate(unique_rows, start=1):
        updated = dict(row)
        updated["claim_id"] = f"clm_{index:06d}"
        final_rows.append(updated)
    return final_rows


def load_claims_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load claims from JSONL."""
    claims: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if isinstance(row, dict):
                claims.append(row)
    return claims


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
        '"preferred_sources":["systematic review","meta-analysis","guideline"]}]}.'
    )
    user = (
        f"Chunk: {chunk_label}\n\n"
        "Task:\n"
        "1) Given the claims below, generate as many high-value validation queries as possible.\n"
        "2) You may merge very similar claims into one query and use one representative claim_id.\n"
        "3) Phrase each query naturally and directly as a question that a human would type in search.\n"
        "   Good: \"Is LDL cholesterol an independent risk factor for heart disease?\"\n"
        "   Good: \"Does reducing saturated fat lower LDL cholesterol?\"\n"
        "   Bad: \"What is the current scientific consensus on whether LDL cholesterol is an "
        "independent risk factor for heart disease?\"\n"
        "4) Keep queries concise and optimized for evidence retrieval.\n"
        "5) Do not use repetitive scaffolding such as \"What is the current scientific consensus on...\".\n"
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


def normalize_query_rows(
    raw_queries: list[dict[str, Any]],
    valid_claim_ids: set[str],
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
        query = _naturalize_query_question(query)
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
        rows.append(
            {
                "claim_id": claim_id,
                "query": query,
                "why_this_query": why_this_query,
                "preferred_sources": normalized_sources,
            }
        )
    return rows


def _query_dedupe_key(row: dict[str, Any]) -> str:
    return re.sub(r"\W+", " ", str(row.get("query", "")).lower()).strip()


def dedupe_queries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate query rows by normalized query text."""
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = _query_dedupe_key(row)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _sources_for_claim_type(claim_type: str) -> list[str]:
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


def _naturalize_query_question(text: str) -> str:
    """Convert repetitive consensus phrasing into short natural questions."""
    query = re.sub(r"\s+", " ", text.strip())
    if not query:
        return ""

    # Strip common repetitive wrappers.
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

    # If already starts with an auxiliary verb, just add '?'.
    if re.match(
        r"(?i)^(is|are|can|could|should|would|do|does|did|has|have|had|will|was|were)\b",
        query,
    ):
        return f"{query}?"

    # Basic statement->question transforms.
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


def _clean_query_terms(claim_text: str, max_terms: int = 12) -> str:
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
    cleaned = _clean_query_terms(claim_text, max_terms=max_terms)
    return {tok for tok in cleaned.split() if tok}


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def generate_heuristic_queries(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
        source_types = _sources_for_claim_type(claim_type)
        query = _naturalize_query_question(claim_text)
        rows.append(
            {
                "claim_id": claim_id,
                "query": query,
                "why_this_query": (
                    "Fallback query for claim validation using high-evidence source types "
                    "matched to claim category."
                ),
                "preferred_sources": source_types,
            }
        )
    return rows


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
    config: OllamaConfig,
    query_model: str,
    chunk_size: int,
    chunk_overlap: int,
) -> list[dict[str, Any]]:
    """Generate deduplicated validation queries from extracted claims."""
    valid_claim_ids = {
        str(claim.get("claim_id", "")).strip()
        for claim in claims
        if str(claim.get("claim_id", "")).strip()
    }
    if not valid_claim_ids:
        return []

    chunks = build_chunks(claims, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    query_rows_raw: list[dict[str, Any]] = []

    for chunk_index, chunk in enumerate(chunks, start=1):
        claims_block = build_claims_block(chunk)
        if not claims_block:
            continue
        messages = build_query_prompt(claims_block, chunk_label=f"{chunk_index}/{len(chunks)}")
        try:
            response_text = ollama_chat(config=config, model=query_model, messages=messages)
        except Exception as exc:  # noqa: BLE001 - prototype tolerance
            console.print(
                f"[red]Query generation failed for chunk {chunk_index}/{len(chunks)}: {exc}[/red]"
            )
            continue

        try:
            payload = _extract_json_object(response_text)
        except ValueError as exc:
            console.print(
                f"[red]Invalid query JSON for chunk {chunk_index}/{len(chunks)}: {exc}[/red]"
            )
            continue

        raw_queries = payload.get("queries", [])
        if not isinstance(raw_queries, list):
            continue
        normalized = normalize_query_rows(raw_queries, valid_claim_ids=valid_claim_ids)
        query_rows_raw.extend(normalized)
        console.print(
            f"[green]{query_model} query chunk {chunk_index}/{len(chunks)}: "
            f"{len(normalized)} queries[/green]"
        )

    deduped_llm_queries = dedupe_queries(query_rows_raw)
    covered_claim_ids = {row["claim_id"] for row in deduped_llm_queries}
    missing_claims = [
        claim
        for claim in claims
        if str(claim.get("claim_id", "")).strip()
        and str(claim.get("claim_id", "")).strip() not in covered_claim_ids
    ]
    if missing_claims:
        console.print(
            f"[yellow]Adding fallback queries for {len(missing_claims)} uncovered claims.[/yellow]"
        )
        deduped_llm_queries.extend(generate_heuristic_queries(missing_claims))

    return dedupe_queries(deduped_llm_queries)


def normalize_claims(
    doc_id: str,
    model: str,
    raw_claims: list[dict[str, Any]],
    start_time_by_seg_id: dict[str, int],
) -> list[dict[str, Any]]:
    """Normalize model output into final JSONL rows."""
    out: list[dict[str, Any]] = []
    for claim in raw_claims:
        if not isinstance(claim, dict):
            continue
        speaker = str(claim.get("speaker", "")).strip()
        claim_text = str(claim.get("claim_text", "")).strip()
        evidence = _normalize_evidence(claim.get("evidence"))
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
        boldness_rating = _normalize_boldness_rating(claim)
        time_range = _derive_time_range(
            claim,
            fallback_start=fallback_start,
            fallback_end=fallback_end,
        )
        out.append(
            {
                "doc_id": doc_id,
                "speaker": speaker,
                "claim_text": claim_text,
                "evidence": evidence,
                "time_range_s": time_range,
                "claim_type": claim_type,
                "boldness_rating": boldness_rating,
                "model": model,
            }
        )
    return out


def load_transcript(path: Path) -> tuple[str, list[dict[str, Any]]]:
    """Load normalized transcript JSON and return doc_id plus segments."""
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    doc_id = str(data.get("doc_id", "")).strip()
    segments = data.get("segments", [])
    if not doc_id:
        raise ValueError("Transcript JSON missing doc_id.")
    if not isinstance(segments, list) or not segments:
        raise ValueError("Transcript JSON missing segments.")
    return doc_id, segments


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write claims to JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False))
            file.write("\n")


def _parse_model_list(models: str) -> list[str]:
    return [model.strip() for model in models.split(",") if model.strip()]


def _validate_chunking(chunk_size: int, chunk_overlap: int, label: str) -> None:
    if chunk_size <= 0:
        raise typer.BadParameter(f"--{label}-size must be > 0")
    if chunk_overlap < 0:
        raise typer.BadParameter(f"--{label}-overlap must be >= 0")
    if chunk_overlap >= chunk_size:
        raise typer.BadParameter(f"--{label}-overlap must be smaller than --{label}-size")


def _validate_common_args(timeout: float, max_segments: int) -> None:
    if timeout <= 0:
        raise typer.BadParameter("--timeout must be > 0")
    if max_segments < 0:
        raise typer.BadParameter("--max-segments must be >= 0")


def _validate_path_exists(path: Path, flag_name: str) -> None:
    if not path.exists():
        raise typer.BadParameter(f"{flag_name} path does not exist: {path}")


def _fetch_available_models(config: OllamaConfig) -> list[str]:
    try:
        return list_ollama_models(config)
    except urllib.error.URLError as exc:
        raise typer.BadParameter(
            f"Could not connect to Ollama at {config.base_url}: {exc}"
        ) from exc


def _warn_missing_models(requested_models: list[str], available_models: list[str]) -> None:
    missing = [name for name in requested_models if name not in available_models]
    if missing:
        console.print(f"[yellow]Requested models not found in /api/tags: {missing}[/yellow]")


def _print_claim_rows(rows: list[dict[str, Any]]) -> None:
    console.print("[bold]Extracted claims[/bold]:")
    for row in rows:
        console.print(
            f"{row.get('claim_id', 'unknown')} | {row.get('model', 'unknown')} | "
            f"{row.get('speaker', 'unknown')} | {row.get('claim_type', 'unknown')} | "
            f"{row.get('claim_text', '')}"
        )


def _print_query_rows(rows: list[dict[str, Any]]) -> None:
    console.print("[bold]Validation queries[/bold]:")
    for row in rows:
        console.print(
            f"{row.get('claim_id', 'unknown')} | {row.get('query', '')} | "
            f"{row.get('why_this_query', '')} | {', '.join(row.get('preferred_sources', []))}"
        )


def run_claim_extraction(
    transcript: Path,
    model_list: list[str],
    config: OllamaConfig,
    max_segments: int,
    chunk_size: int,
    chunk_overlap: int,
) -> list[dict[str, Any]]:
    """Run transcript claim extraction and return deduplicated claim rows."""
    if not model_list:
        raise typer.BadParameter("No models provided.")

    _validate_path_exists(transcript, "--transcript")
    _validate_common_args(timeout=config.timeout, max_segments=max_segments)
    _validate_chunking(chunk_size=chunk_size, chunk_overlap=chunk_overlap, label="chunk")

    doc_id, segments = load_transcript(transcript)
    if max_segments > 0:
        segments = segments[:max_segments]
    chunks = build_chunks(segments, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    start_time_by_seg_id = {
        str(segment.get("seg_id", "")).strip(): int(segment.get("start_time_s", 0))
        for segment in segments
        if str(segment.get("seg_id", "")).strip()
    }

    all_rows_raw: list[dict[str, Any]] = []
    for model in model_list:
        console.print(f"[cyan]Running extraction with model:[/cyan] {model}")
        model_rows: list[dict[str, Any]] = []
        for chunk_index, chunk in enumerate(chunks, start=1):
            segment_block = build_segment_block(chunk, max_segments=len(chunk))
            messages = build_prompt(
                doc_id,
                segment_block,
                chunk_label=f"{chunk_index}/{len(chunks)}",
            )
            try:
                response_text = ollama_chat(config=config, model=model, messages=messages)
            except urllib.error.URLError as exc:
                console.print(f"[red]Failed request for model {model}, chunk {chunk_index}: {exc}[/red]")
                continue
            except Exception as exc:  # noqa: BLE001 - keep prototype error handling simple
                console.print(f"[red]Model {model}, chunk {chunk_index} failed: {exc}[/red]")
                continue

            try:
                payload = _extract_json_object(response_text)
            except ValueError as exc:
                console.print(
                    f"[red]Could not parse JSON response for {model}, chunk {chunk_index}: {exc}[/red]"
                )
                continue

            claims = payload.get("claims", [])
            if not isinstance(claims, list):
                console.print(
                    f"[yellow]Model {model}, chunk {chunk_index} returned no claims list.[/yellow]"
                )
                continue

            normalized_rows = normalize_claims(
                doc_id=doc_id,
                model=model,
                raw_claims=claims,
                start_time_by_seg_id=start_time_by_seg_id,
            )
            model_rows.extend(normalized_rows)
            console.print(
                f"[green]{model} chunk {chunk_index}/{len(chunks)}: "
                f"{len(normalized_rows)} claims[/green]"
            )

        deduped_model_rows = dedupe_and_assign_claim_ids(model_rows)
        all_rows_raw.extend(deduped_model_rows)
        console.print(
            f"[green]Model {model} produced {len(deduped_model_rows)} unique claims "
            f"across {len(chunks)} chunks.[/green]"
        )

    return dedupe_and_assign_claim_ids(all_rows_raw)


def run_query_generation(
    claims: list[dict[str, Any]],
    config: OllamaConfig,
    query_model: str | None,
    model_list: list[str],
    available_models: list[str],
    chunk_size: int,
    chunk_overlap: int,
) -> list[dict[str, Any]]:
    """Generate validation queries from existing claim rows."""
    _validate_chunking(chunk_size=chunk_size, chunk_overlap=chunk_overlap, label="query-chunk")
    selected_query_model = choose_query_model(
        query_model=query_model,
        model_list=model_list,
        available_models=available_models,
    )
    if selected_query_model is None:
        console.print(
            "[yellow]Skipping query generation: no model available. "
            "Use --query-model or install a local Ollama model.[/yellow]"
        )
        return []

    console.print(f"[cyan]Generating validation queries with:[/cyan] {selected_query_model}")
    return generate_validation_queries(
        claims=claims,
        config=config,
        query_model=selected_query_model,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )


app = typer.Typer(help="Prototype commands for extracting health claims and validation queries.")


@app.command("extract-claims")
def extract_claims_command(
    transcript: Path = typer.Option(
        DEFAULT_INPUT,
        "--transcript",
        help="Path to normalized transcript JSON with segments.",
    ),
    output: Path = typer.Option(
        DEFAULT_OUTPUT,
        "--output",
        help="Output JSONL file path.",
    ),
    models: str = typer.Option(
        DEFAULT_MODELS,
        "--models",
        help="Comma-separated Ollama model names to run for comparison.",
    ),
    ollama_url: str = typer.Option(
        DEFAULT_OLLAMA_URL,
        "--ollama-url",
        help="Ollama base URL.",
    ),
    timeout: float = typer.Option(
        180.0,
        "--timeout",
        help="Ollama request timeout in seconds.",
    ),
    max_segments: int = typer.Option(
        0,
        "--max-segments",
        help="Optional cap on transcript segments to process (0 = all).",
    ),
    chunk_size: int = typer.Option(
        45,
        "--chunk-size",
        help="Transcript segments per model call.",
    ),
    chunk_overlap: int = typer.Option(
        12,
        "--chunk-overlap",
        help="Segment overlap between adjacent chunks.",
    ),
    list_claims: bool = typer.Option(
        True,
        "--list-claims/--no-list-claims",
        help="Print all extracted claims after writing output.",
    ),
) -> None:
    """Extract claims from transcript segments and write claims JSONL."""
    model_list = _parse_model_list(models)
    if not model_list:
        raise typer.BadParameter("No models provided.")
    config = OllamaConfig(base_url=ollama_url, timeout=timeout)
    available_models = _fetch_available_models(config)
    _warn_missing_models(model_list, available_models)

    all_rows = run_claim_extraction(
        transcript=transcript,
        model_list=model_list,
        config=config,
        max_segments=max_segments,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    write_jsonl(output, all_rows)
    console.print(f"[bold green]Wrote {len(all_rows)} claims to {output}[/bold green]")
    if list_claims:
        _print_claim_rows(all_rows)


@app.command("generate-queries")
def generate_queries_command(
    claims_input: Path = typer.Option(
        DEFAULT_OUTPUT,
        "--claims-input",
        help="Existing claims JSONL used as query-generation input.",
    ),
    queries_output: Path = typer.Option(
        DEFAULT_QUERIES_OUTPUT,
        "--queries-output",
        help="Output JSONL file for validation queries.",
    ),
    models: str = typer.Option(
        DEFAULT_MODELS,
        "--models",
        help="Comma-separated model names used as fallback selection order.",
    ),
    query_model: str | None = typer.Option(
        None,
        "--query-model",
        help="Explicit model for query generation.",
    ),
    ollama_url: str = typer.Option(
        DEFAULT_OLLAMA_URL,
        "--ollama-url",
        help="Ollama base URL.",
    ),
    timeout: float = typer.Option(
        180.0,
        "--timeout",
        help="Ollama request timeout in seconds.",
    ),
    query_chunk_size: int = typer.Option(
        25,
        "--query-chunk-size",
        help="Claims per query-generation model call.",
    ),
    query_chunk_overlap: int = typer.Option(
        5,
        "--query-chunk-overlap",
        help="Claims overlap between query-generation chunks.",
    ),
    list_queries: bool = typer.Option(
        True,
        "--list-queries/--no-list-queries",
        help="Print generated validation queries after writing output.",
    ),
) -> None:
    """Generate validation queries from an existing claims JSONL file."""
    _validate_path_exists(claims_input, "--claims-input")
    _validate_common_args(timeout=timeout, max_segments=0)

    model_list = _parse_model_list(models)
    config = OllamaConfig(base_url=ollama_url, timeout=timeout)
    available_models = _fetch_available_models(config)
    _warn_missing_models(model_list, available_models)

    claims = load_claims_jsonl(claims_input)
    console.print(f"[green]Loaded {len(claims)} claims from {claims_input}[/green]")
    query_rows = run_query_generation(
        claims=claims,
        config=config,
        query_model=query_model,
        model_list=model_list,
        available_models=available_models,
        chunk_size=query_chunk_size,
        chunk_overlap=query_chunk_overlap,
    )
    write_jsonl(queries_output, query_rows)
    console.print(
        f"[bold green]Wrote {len(query_rows)} validation queries to {queries_output}[/bold green]"
    )
    if list_queries:
        _print_query_rows(query_rows)


@app.command("run-pipeline")
def run_pipeline_command(
    transcript: Path = typer.Option(
        DEFAULT_INPUT,
        "--transcript",
        help="Path to normalized transcript JSON with segments.",
    ),
    output: Path = typer.Option(
        DEFAULT_OUTPUT,
        "--output",
        help="Output JSONL file path for extracted claims.",
    ),
    queries_output: Path = typer.Option(
        DEFAULT_QUERIES_OUTPUT,
        "--queries-output",
        help="Output JSONL file path for validation queries.",
    ),
    models: str = typer.Option(
        DEFAULT_MODELS,
        "--models",
        help="Comma-separated Ollama model names to run for extraction.",
    ),
    query_model: str | None = typer.Option(
        None,
        "--query-model",
        help="Model for query generation (default: first available model from --models).",
    ),
    ollama_url: str = typer.Option(
        DEFAULT_OLLAMA_URL,
        "--ollama-url",
        help="Ollama base URL.",
    ),
    timeout: float = typer.Option(
        180.0,
        "--timeout",
        help="Ollama request timeout in seconds.",
    ),
    max_segments: int = typer.Option(
        0,
        "--max-segments",
        help="Optional cap on transcript segments to process (0 = all).",
    ),
    chunk_size: int = typer.Option(
        45,
        "--chunk-size",
        help="Transcript segments per model call.",
    ),
    chunk_overlap: int = typer.Option(
        12,
        "--chunk-overlap",
        help="Segment overlap between adjacent chunks.",
    ),
    query_chunk_size: int = typer.Option(
        25,
        "--query-chunk-size",
        help="Claims per query-generation model call.",
    ),
    query_chunk_overlap: int = typer.Option(
        5,
        "--query-chunk-overlap",
        help="Claims overlap between query-generation chunks.",
    ),
    list_claims: bool = typer.Option(
        True,
        "--list-claims/--no-list-claims",
        help="Print extracted claims after writing output.",
    ),
    list_queries: bool = typer.Option(
        True,
        "--list-queries/--no-list-queries",
        help="Print generated validation queries after writing output.",
    ),
) -> None:
    """Run extraction and query generation end-to-end."""
    model_list = _parse_model_list(models)
    if not model_list:
        raise typer.BadParameter("No models provided.")
    config = OllamaConfig(base_url=ollama_url, timeout=timeout)
    available_models = _fetch_available_models(config)
    _warn_missing_models(model_list, available_models)

    all_rows = run_claim_extraction(
        transcript=transcript,
        model_list=model_list,
        config=config,
        max_segments=max_segments,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    write_jsonl(output, all_rows)
    console.print(f"[bold green]Wrote {len(all_rows)} claims to {output}[/bold green]")
    if list_claims:
        _print_claim_rows(all_rows)

    query_rows = run_query_generation(
        claims=all_rows,
        config=config,
        query_model=query_model,
        model_list=model_list,
        available_models=available_models,
        chunk_size=query_chunk_size,
        chunk_overlap=query_chunk_overlap,
    )
    write_jsonl(queries_output, query_rows)
    console.print(
        f"[bold green]Wrote {len(query_rows)} validation queries to {queries_output}[/bold green]"
    )
    if list_queries:
        _print_query_rows(query_rows)


if __name__ == "__main__":
    app()
