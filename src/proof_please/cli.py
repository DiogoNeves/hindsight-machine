"""CLI entrypoints for proof-please."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import typer
from rich.console import Console

from proof_please.config import AppConfig
from proof_please.core.io import load_claims_jsonl, write_jsonl
from proof_please.core.printing import print_claim_rows, print_query_rows
from proof_please.db import get_connection, init_schema
from proof_please.pipeline.models import ModelBackendConfig
from proof_please.pipeline.pipeline_runner import (
    fetch_available_models,
    find_missing_models,
    parse_model_list,
    run_claim_extraction,
    run_query_generation,
    validate_common_args,
    validate_path_exists,
)

app = typer.Typer(
    no_args_is_help=True,
    help="Commands for transcript claim extraction and validation-query generation.",
)
console = Console()

DEFAULT_INPUT = Path("data/transcripts/norm/web__the-ready-state__layne-norton__2022-10-20__v1.json")
DEFAULT_OUTPUT = Path("data/claims.jsonl")
DEFAULT_QUERIES_OUTPUT = Path("data/claim_queries.jsonl")
DEFAULT_MODELS = "gpt-oss:20b,qwen3:4b"
DEFAULT_BACKEND_URL = "http://127.0.0.1:11434"

TRANSCRIPT_OPTION = typer.Option(
    DEFAULT_INPUT,
    "--transcript",
    help="Path to normalized transcript JSON with segments.",
)
CLAIMS_OUTPUT_OPTION = typer.Option(
    DEFAULT_OUTPUT,
    "--output",
    help="Output JSONL file path for extracted claims.",
)
CLAIMS_INPUT_OPTION = typer.Option(
    DEFAULT_OUTPUT,
    "--claims-input",
    help="Existing claims JSONL used as query-generation input.",
)
QUERIES_OUTPUT_OPTION = typer.Option(
    DEFAULT_QUERIES_OUTPUT,
    "--queries-output",
    help="Output JSONL file for validation queries.",
)
MODELS_OPTION = typer.Option(
    DEFAULT_MODELS,
    "--models",
    help="Comma-separated model names for extraction and query-model fallback selection.",
)
QUERY_MODEL_OPTION = typer.Option(
    None,
    "--query-model",
    help="Model for query generation (default: first available model from --models).",
)
BACKEND_URL_OPTION = typer.Option(
    DEFAULT_BACKEND_URL,
    "--backend-url",
    "--ollama-url",
    help="Model backend base URL.",
)
TIMEOUT_OPTION = typer.Option(
    180.0,
    "--timeout",
    help="Model backend request timeout in seconds.",
)
MAX_SEGMENTS_OPTION = typer.Option(
    0,
    "--max-segments",
    help="Optional cap on transcript segments to process (0 = all).",
)
CHUNK_SIZE_OPTION = typer.Option(
    45,
    "--chunk-size",
    help="Transcript segments per model call.",
)
CHUNK_OVERLAP_OPTION = typer.Option(
    12,
    "--chunk-overlap",
    help="Segment overlap between adjacent chunks.",
)
QUERY_CHUNK_SIZE_OPTION = typer.Option(
    25,
    "--query-chunk-size",
    help="Claims per query-generation model call.",
)
QUERY_CHUNK_OVERLAP_OPTION = typer.Option(
    5,
    "--query-chunk-overlap",
    help="Claims overlap between query-generation chunks.",
)
LIST_CLAIMS_OPTION = typer.Option(
    True,
    "--list-claims/--no-list-claims",
    help="Print extracted claims after writing output.",
)
LIST_QUERIES_OPTION = typer.Option(
    True,
    "--list-queries/--no-list-queries",
    help="Print generated validation queries after writing output.",
)


def _status(message: str) -> None:
    console.print(f"[dim]{message}[/dim]")


def _to_bad_parameter(exc: Exception) -> typer.BadParameter:
    return typer.BadParameter(str(exc))


def _backend_config(backend_url: str, timeout: float) -> ModelBackendConfig:
    return ModelBackendConfig(base_url=backend_url, timeout=timeout)


@app.command("config")
def show_config() -> None:
    """Print the current app configuration."""
    cfg = AppConfig()
    console.print(f"[bold]DuckDB path:[/bold] {cfg.duckdb_path}")


@app.command("init-db")
def initialize_database() -> None:
    """Create the initial DuckDB database and schema."""
    cfg = AppConfig()
    with get_connection(cfg.duckdb_path) as conn:
        init_schema(conn)
    console.print(f"[green]Initialized DuckDB:[/green] {cfg.duckdb_path}")


@app.command("extract-claims")
def extract_claims_command(
    transcript: Path = TRANSCRIPT_OPTION,
    output: Path = CLAIMS_OUTPUT_OPTION,
    models: str = MODELS_OPTION,
    backend_url: str = BACKEND_URL_OPTION,
    timeout: float = TIMEOUT_OPTION,
    max_segments: int = MAX_SEGMENTS_OPTION,
    chunk_size: int = CHUNK_SIZE_OPTION,
    chunk_overlap: int = CHUNK_OVERLAP_OPTION,
    list_claims: bool = LIST_CLAIMS_OPTION,
) -> None:
    """Extract claims from transcript segments and write claims JSONL."""
    model_list = parse_model_list(models)

    try:
        validate_common_args(timeout=timeout, max_segments=max_segments)
        if not model_list:
            raise ValueError("No models provided.")

        config = _backend_config(backend_url=backend_url, timeout=timeout)
        available_models = fetch_available_models(config)
        missing_models = find_missing_models(model_list, available_models)
        if missing_models:
            console.print(f"[yellow]Requested models not found in model list: {missing_models}[/yellow]")

        run_id = f"run_{uuid4().hex[:12]}"
        all_rows = run_claim_extraction(
            transcript=transcript,
            model_list=model_list,
            config=config,
            max_segments=max_segments,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            on_status=_status,
            run_id=run_id,
        )
    except (ValueError, FileNotFoundError, ConnectionError) as exc:
        raise _to_bad_parameter(exc) from exc

    write_jsonl(output, all_rows)
    console.print(f"[bold green]Wrote {len(all_rows)} claims to {output}[/bold green]")
    if list_claims:
        print_claim_rows(all_rows, console)


@app.command("generate-queries")
def generate_queries_command(
    claims_input: Path = CLAIMS_INPUT_OPTION,
    queries_output: Path = QUERIES_OUTPUT_OPTION,
    models: str = MODELS_OPTION,
    query_model: str | None = QUERY_MODEL_OPTION,
    backend_url: str = BACKEND_URL_OPTION,
    timeout: float = TIMEOUT_OPTION,
    query_chunk_size: int = QUERY_CHUNK_SIZE_OPTION,
    query_chunk_overlap: int = QUERY_CHUNK_OVERLAP_OPTION,
    list_queries: bool = LIST_QUERIES_OPTION,
) -> None:
    """Generate validation queries from an existing claims JSONL file."""
    model_list = parse_model_list(models)

    try:
        validate_path_exists(claims_input, "--claims-input")
        validate_common_args(timeout=timeout, max_segments=0)

        config = _backend_config(backend_url=backend_url, timeout=timeout)
        available_models = fetch_available_models(config)
        missing_models = find_missing_models(model_list, available_models)
        if missing_models:
            console.print(f"[yellow]Requested models not found in model list: {missing_models}[/yellow]")

        claims = load_claims_jsonl(claims_input)
        console.print(f"[green]Loaded {len(claims)} claims from {claims_input}[/green]")
        run_id = f"run_{uuid4().hex[:12]}"
        query_rows = run_query_generation(
            claims=claims,
            config=config,
            query_model=query_model,
            model_list=model_list,
            available_models=available_models,
            chunk_size=query_chunk_size,
            chunk_overlap=query_chunk_overlap,
            on_status=_status,
            run_id=run_id,
        )
    except (ValueError, FileNotFoundError, ConnectionError) as exc:
        raise _to_bad_parameter(exc) from exc

    write_jsonl(queries_output, query_rows)
    console.print(
        f"[bold green]Wrote {len(query_rows)} validation queries to {queries_output}[/bold green]"
    )
    if list_queries:
        print_query_rows(query_rows, console)


@app.command("run-pipeline")
def run_pipeline_command(
    transcript: Path = TRANSCRIPT_OPTION,
    output: Path = CLAIMS_OUTPUT_OPTION,
    queries_output: Path = QUERIES_OUTPUT_OPTION,
    models: str = MODELS_OPTION,
    query_model: str | None = QUERY_MODEL_OPTION,
    backend_url: str = BACKEND_URL_OPTION,
    timeout: float = TIMEOUT_OPTION,
    max_segments: int = MAX_SEGMENTS_OPTION,
    chunk_size: int = CHUNK_SIZE_OPTION,
    chunk_overlap: int = CHUNK_OVERLAP_OPTION,
    query_chunk_size: int = QUERY_CHUNK_SIZE_OPTION,
    query_chunk_overlap: int = QUERY_CHUNK_OVERLAP_OPTION,
    list_claims: bool = LIST_CLAIMS_OPTION,
    list_queries: bool = LIST_QUERIES_OPTION,
) -> None:
    """Run extraction and query generation end-to-end."""
    model_list = parse_model_list(models)

    try:
        validate_common_args(timeout=timeout, max_segments=max_segments)
        if not model_list:
            raise ValueError("No models provided.")

        config = _backend_config(backend_url=backend_url, timeout=timeout)
        available_models = fetch_available_models(config)
        missing_models = find_missing_models(model_list, available_models)
        if missing_models:
            console.print(f"[yellow]Requested models not found in model list: {missing_models}[/yellow]")
            model_list = [model for model in model_list if model not in missing_models]
            if not model_list:
                raise ValueError(
                    "None of the requested models are available. Update --models or install one locally."
                )

        run_id = f"run_{uuid4().hex[:12]}"
        all_rows = run_claim_extraction(
            transcript=transcript,
            model_list=model_list,
            config=config,
            max_segments=max_segments,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            on_status=_status,
            run_id=run_id,
        )
        query_rows = run_query_generation(
            claims=all_rows,
            config=config,
            query_model=query_model,
            model_list=model_list,
            available_models=available_models,
            chunk_size=query_chunk_size,
            chunk_overlap=query_chunk_overlap,
            on_status=_status,
            run_id=run_id,
        )
    except (ValueError, FileNotFoundError, ConnectionError) as exc:
        raise _to_bad_parameter(exc) from exc

    write_jsonl(output, all_rows)
    console.print(f"[bold green]Wrote {len(all_rows)} claims to {output}[/bold green]")
    if list_claims:
        print_claim_rows(all_rows, console)

    write_jsonl(queries_output, query_rows)
    console.print(
        f"[bold green]Wrote {len(query_rows)} validation queries to {queries_output}[/bold green]"
    )
    if list_queries:
        print_query_rows(query_rows, console)


def main() -> None:
    """Console script entry point."""
    app()


if __name__ == "__main__":
    main()
