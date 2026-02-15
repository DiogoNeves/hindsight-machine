"""File-loading helpers for the Streamlit data explorer."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from proof_please.explorer.models import ClaimRow, QueryRow
from proof_please.pipeline.models import TranscriptDocument


@dataclass(frozen=True)
class ExplorerDataset:
    """Loaded data artifacts consumed by the explorer UI."""

    claims: list[ClaimRow]
    queries: list[QueryRow]
    transcripts_by_doc_id: dict[str, TranscriptDocument]
    warnings: tuple[str, ...] = ()


def _load_jsonl_dict_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            stripped = line.strip()
            if not stripped:
                continue
            raw_row = json.loads(stripped)
            if isinstance(raw_row, dict):
                rows.append(raw_row)
    return rows


def _load_claim_rows(path: Path) -> tuple[list[ClaimRow], list[str]]:
    claims: list[ClaimRow] = []
    warnings: list[str] = []
    for index, row in enumerate(_load_jsonl_dict_rows(path), start=1):
        try:
            claims.append(ClaimRow.model_validate(row))
        except Exception as exc:  # noqa: BLE001 - display warning but continue loading
            warnings.append(f"Skipped invalid claim row {index}: {exc}")
    return claims, warnings


def _load_query_rows(path: Path) -> tuple[list[QueryRow], list[str]]:
    queries: list[QueryRow] = []
    warnings: list[str] = []
    for index, row in enumerate(_load_jsonl_dict_rows(path), start=1):
        try:
            queries.append(QueryRow.model_validate(row))
        except Exception as exc:  # noqa: BLE001 - display warning but continue loading
            warnings.append(f"Skipped invalid query row {index}: {exc}")
    return queries, warnings


def _iter_transcript_files(transcripts_path: Path) -> list[Path]:
    if transcripts_path.is_file():
        if transcripts_path.suffix.lower() != ".json":
            raise ValueError(f"Transcript path must be a .json file: {transcripts_path}")
        return [transcripts_path]

    if transcripts_path.is_dir():
        files = sorted(path for path in transcripts_path.rglob("*.json") if path.is_file())
        if files:
            return files
        raise FileNotFoundError(f"No transcript JSON files found in directory: {transcripts_path}")

    raise FileNotFoundError(f"Transcript path does not exist: {transcripts_path}")


def _load_transcripts_by_doc_id(transcripts_path: Path) -> tuple[dict[str, TranscriptDocument], list[str]]:
    docs_by_id: dict[str, TranscriptDocument] = {}
    warnings: list[str] = []

    for path in _iter_transcript_files(transcripts_path):
        try:
            with path.open("r", encoding="utf-8") as file:
                raw_payload = json.load(file)
        except json.JSONDecodeError as exc:
            warnings.append(f"Skipped transcript {path}: invalid JSON ({exc})")
            continue

        try:
            document = TranscriptDocument.model_validate(raw_payload)
        except Exception as exc:  # noqa: BLE001 - display warning but continue loading
            warnings.append(f"Skipped transcript {path}: invalid schema ({exc})")
            continue

        if not document.doc_id:
            warnings.append(f"Skipped transcript {path}: missing doc_id")
            continue
        if document.doc_id in docs_by_id:
            warnings.append(
                f"Skipped transcript {path}: duplicate doc_id '{document.doc_id}' already loaded"
            )
            continue

        docs_by_id[document.doc_id] = document

    return docs_by_id, warnings


def _validate_existing_file(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} path does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"{label} path must be a file: {path}")


def load_dataset(claims_path: Path, queries_path: Path, transcripts_path: Path) -> ExplorerDataset:
    """Load claims, queries, and transcripts from local JSON artifacts."""
    claims_path = claims_path.expanduser()
    queries_path = queries_path.expanduser()
    transcripts_path = transcripts_path.expanduser()

    _validate_existing_file(claims_path, "Claims")
    _validate_existing_file(queries_path, "Queries")

    claims, claim_warnings = _load_claim_rows(claims_path)
    queries, query_warnings = _load_query_rows(queries_path)
    transcripts_by_doc_id, transcript_warnings = _load_transcripts_by_doc_id(transcripts_path)

    all_warnings = tuple([*claim_warnings, *query_warnings, *transcript_warnings])
    return ExplorerDataset(
        claims=claims,
        queries=queries,
        transcripts_by_doc_id=transcripts_by_doc_id,
        warnings=all_warnings,
    )
