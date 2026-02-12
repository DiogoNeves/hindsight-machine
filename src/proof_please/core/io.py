"""I/O helpers for transcripts and JSONL artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from proof_please.pipeline.models import TranscriptDocument


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the last JSON object from a text response."""
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


def load_transcript(path: Path) -> tuple[str, list[dict[str, Any]]]:
    """Load normalized transcript JSON and return doc_id plus segments."""
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    doc = TranscriptDocument.model_validate(data)
    if not doc.doc_id:
        raise ValueError("Transcript JSON missing doc_id.")
    if not doc.segments:
        raise ValueError("Transcript JSON missing segments.")
    return doc.doc_id, [segment.model_dump() for segment in doc.segments]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write rows to JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False))
            file.write("\n")
