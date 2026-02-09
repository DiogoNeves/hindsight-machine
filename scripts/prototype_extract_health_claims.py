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
        '"time_range_s":{"start":0,"end":0},"claim_type":"medical_risk"}]}. '
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
        "5) Prefer recall over precision: include explicit claims about risk, causality, effects, "
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
        "Every `query` must be a single question about scientific consensus for a claim "
        "or a small set of similar claims. "
        "Return JSON only with this shape: "
        '{"queries":[{"claim_id":"clm_000001","query":"...","why_this_query":"...",'
        '"preferred_sources":["systematic review","meta-analysis","guideline"]}]}.'
    )
    user = (
        f"Chunk: {chunk_label}\n\n"
        "Task:\n"
        "1) Given the claims below, generate as many high-value validation queries as possible.\n"
        "2) You may merge very similar claims into one query and use one representative claim_id.\n"
        "3) Write each query as a consensus question, e.g. "
        "\"What is the current scientific consensus on whether LDL cholesterol is an "
        "independent risk factor for heart disease?\"\n"
        "4) Keep queries concise and optimized for evidence retrieval.\n"
        "5) Do not append source types inside `query`; keep source types only in "
        "`preferred_sources`.\n"
        "6) Prefer source types like systematic review, meta-analysis, guideline, "
        "mendelian randomisation, RCT.\n"
        "7) Return JSON only.\n\n"
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
        if query and "?" not in query:
            normalized_query = query.rstrip(" .")
            query = f"What is the current scientific consensus on {normalized_query}?"
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
        query = f"What is the current scientific consensus on the claim that {claim_text}?"
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


def main(
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
    queries_output: Path = typer.Option(
        DEFAULT_QUERIES_OUTPUT,
        "--queries-output",
        help="Output JSONL file for validation queries.",
    ),
    models: str = typer.Option(
        DEFAULT_MODELS,
        "--models",
        help="Comma-separated Ollama model names to run for comparison.",
    ),
    query_model: str | None = typer.Option(
        None,
        "--query-model",
        help="Model for query generation (default: first available model from --models).",
    ),
    claims_input: Path | None = typer.Option(
        None,
        "--claims-input",
        help="Existing claims JSONL to use as query input (skip extraction).",
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
    generate_queries: bool = typer.Option(
        True,
        "--generate-queries/--no-generate-queries",
        help="Generate validation queries from extracted claims.",
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
    list_models_only: bool = typer.Option(
        False,
        "--list-models",
        help="Only list installed Ollama models and exit.",
    ),
    list_claims: bool = typer.Option(
        True,
        "--list-claims/--no-list-claims",
        help="Print all extracted claims after writing output.",
    ),
) -> None:
    """Run claim extraction with one or more Ollama models and write JSONL output."""
    if not transcript.exists():
        raise typer.BadParameter(f"Transcript path does not exist: {transcript}")
    if max_segments < 0:
        raise typer.BadParameter("--max-segments must be >= 0")
    if chunk_size <= 0:
        raise typer.BadParameter("--chunk-size must be > 0")
    if chunk_overlap < 0:
        raise typer.BadParameter("--chunk-overlap must be >= 0")
    if chunk_overlap >= chunk_size:
        raise typer.BadParameter("--chunk-overlap must be smaller than --chunk-size")
    if query_chunk_size <= 0:
        raise typer.BadParameter("--query-chunk-size must be > 0")
    if query_chunk_overlap < 0:
        raise typer.BadParameter("--query-chunk-overlap must be >= 0")
    if query_chunk_overlap >= query_chunk_size:
        raise typer.BadParameter("--query-chunk-overlap must be smaller than --query-chunk-size")
    if claims_input is not None and not claims_input.exists():
        raise typer.BadParameter(f"--claims-input path does not exist: {claims_input}")

    model_list = [model.strip() for model in models.split(",") if model.strip()]
    if not model_list and claims_input is None:
        raise typer.BadParameter("No models provided.")

    config = OllamaConfig(base_url=ollama_url, timeout=timeout)

    try:
        available_models = list_ollama_models(config)
        if available_models:
            console.print("[bold]Installed Ollama models[/bold]:")
            for model_name in available_models:
                console.print(f"  - {model_name}")
        else:
            console.print("[yellow]No models returned by /api/tags.[/yellow]")
        missing = [name for name in model_list if name not in available_models]
        if missing:
            console.print(f"[yellow]Requested models not found in /api/tags: {missing}[/yellow]")
    except urllib.error.URLError as exc:
        raise typer.BadParameter(f"Could not connect to Ollama at {ollama_url}: {exc}") from exc

    if list_models_only:
        return

    all_rows: list[dict[str, Any]]
    if claims_input is not None:
        all_rows = load_claims_jsonl(claims_input)
        console.print(f"[green]Loaded {len(all_rows)} claims from {claims_input}[/green]")
    else:
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
                    console.print(
                        f"[red]Failed request for model {model}, chunk {chunk_index}: {exc}[/red]"
                    )
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

        all_rows = dedupe_and_assign_claim_ids(all_rows_raw)
        write_jsonl(output, all_rows)
        console.print(f"[bold green]Wrote {len(all_rows)} claims to {output}[/bold green]")

    if list_claims:
        console.print("[bold]Extracted claims[/bold]:")
        for row in all_rows:
            console.print(
                f"{row.get('claim_id', 'unknown')} | {row.get('model', 'unknown')} | "
                f"{row.get('speaker', 'unknown')} | {row.get('claim_type', 'unknown')} | "
                f"{row.get('claim_text', '')}"
            )

    if generate_queries:
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
            return

        console.print(f"[cyan]Generating validation queries with:[/cyan] {selected_query_model}")
        query_rows = generate_validation_queries(
            claims=all_rows,
            config=config,
            query_model=selected_query_model,
            chunk_size=query_chunk_size,
            chunk_overlap=query_chunk_overlap,
        )
        write_jsonl(queries_output, query_rows)
        console.print(
            f"[bold green]Wrote {len(query_rows)} validation queries to {queries_output}[/bold green]"
        )
        console.print("[bold]Validation queries[/bold]:")
        for row in query_rows:
            console.print(
                f"{row['claim_id']} | {row['query']} | {row['why_this_query']} | "
                f"{', '.join(row['preferred_sources'])}"
            )


if __name__ == "__main__":
    typer.run(main)
