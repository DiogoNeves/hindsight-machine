"""Validated row models for the Streamlit data explorer."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


class EvidenceRow(BaseModel):
    """Claim evidence reference to a transcript segment."""

    model_config = ConfigDict(extra="ignore")

    seg_id: str
    quote: str = ""

    @field_validator("seg_id", "quote", mode="before")
    @classmethod
    def _normalize_text_fields(cls, value: Any) -> str:
        return _normalize_text(value)

    @field_validator("seg_id")
    @classmethod
    def _require_seg_id(cls, value: str) -> str:
        if not value:
            raise ValueError("Evidence seg_id is required.")
        return value


class ClaimRow(BaseModel):
    """Explorer-friendly claim row parsed from claims JSONL."""

    model_config = ConfigDict(extra="allow")

    claim_id: str
    doc_id: str
    speaker: str = ""
    claim_text: str
    claim_type: str = "other"
    boldness_rating: int | None = None
    model: str = ""
    evidence: list[EvidenceRow] = Field(default_factory=list)
    time_range_s: dict[str, int] = Field(default_factory=dict)

    @field_validator(
        "claim_id",
        "doc_id",
        "speaker",
        "claim_text",
        "claim_type",
        "model",
        mode="before",
    )
    @classmethod
    def _normalize_text_fields(cls, value: Any) -> str:
        return _normalize_text(value)

    @field_validator("claim_id", "doc_id", "claim_text")
    @classmethod
    def _require_non_empty_fields(cls, value: str) -> str:
        if not value:
            raise ValueError("Required claim field is empty.")
        return value

    @field_validator("boldness_rating", mode="before")
    @classmethod
    def _normalize_boldness_rating(cls, value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @field_validator("time_range_s", mode="before")
    @classmethod
    def _normalize_time_range(cls, value: Any) -> dict[str, int]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, int] = {}
        for key in ("start", "end"):
            if key not in value:
                continue
            try:
                normalized[key] = int(value[key])
            except (TypeError, ValueError):
                continue
        return normalized


class QueryRow(BaseModel):
    """Explorer-friendly validation-query row parsed from query JSONL."""

    model_config = ConfigDict(extra="allow")

    claim_id: str
    query: str
    why_this_query: str = ""
    preferred_sources: list[str] = Field(default_factory=list)

    @field_validator("claim_id", "query", "why_this_query", mode="before")
    @classmethod
    def _normalize_text_fields(cls, value: Any) -> str:
        return _normalize_text(value)

    @field_validator("claim_id", "query")
    @classmethod
    def _require_non_empty_fields(cls, value: str) -> str:
        if not value:
            raise ValueError("Required query field is empty.")
        return value

    @field_validator("preferred_sources", mode="before")
    @classmethod
    def _normalize_sources(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [_normalize_text(item) for item in value if _normalize_text(item)]
