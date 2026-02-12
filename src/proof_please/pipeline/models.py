"""Pydantic models for the health-claims pipeline."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ALLOWED_CLAIM_TYPES = {
    "medical_risk",
    "treatment_effect",
    "nutrition_claim",
    "exercise_claim",
    "epidemiology",
    "other",
}


class ModelBackendConfig(BaseModel):
    """Runtime config for model backend calls."""

    model_config = ConfigDict(extra="ignore")

    base_url: str
    timeout: float


class TranscriptSegment(BaseModel):
    """Normalized transcript segment."""

    model_config = ConfigDict(extra="allow")

    seg_id: str = ""
    speaker: str = ""
    start_time_s: int = 0
    text: str = ""

    @field_validator("seg_id", "speaker", "text", mode="before")
    @classmethod
    def _normalize_string(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("start_time_s", mode="before")
    @classmethod
    def _normalize_start_time(cls, value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0


class TranscriptDocument(BaseModel):
    """Normalized transcript document payload."""

    model_config = ConfigDict(extra="allow")

    doc_id: str = ""
    segments: list[TranscriptSegment] = Field(default_factory=list)
    source: dict[str, Any] = Field(default_factory=dict)
    episode: dict[str, Any] = Field(default_factory=dict)

    @field_validator("doc_id", mode="before")
    @classmethod
    def _normalize_doc_id(cls, value: Any) -> str:
        return str(value or "").strip()


class EvidenceItem(BaseModel):
    """Evidence row extracted for a claim."""

    model_config = ConfigDict(extra="ignore")

    seg_id: str
    quote: str

    @field_validator("seg_id", "quote", mode="before")
    @classmethod
    def _normalize_required_string(cls, value: Any) -> str:
        return str(value or "").strip()


class TimeRange(BaseModel):
    """Time range in seconds."""

    model_config = ConfigDict(extra="ignore")

    start: int = 0
    end: int = 0

    @field_validator("start", "end", mode="before")
    @classmethod
    def _normalize_time_value(cls, value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @model_validator(mode="after")
    def _ensure_non_decreasing(self) -> TimeRange:
        if self.end < self.start:
            self.end = self.start
        return self


class ClaimRecord(BaseModel):
    """Final normalized claim row written to JSONL."""

    model_config = ConfigDict(extra="ignore")

    doc_id: str
    speaker: str
    claim_text: str
    evidence: list[EvidenceItem]
    time_range_s: TimeRange
    claim_type: str = "other"
    boldness_rating: int = 2
    model: str
    claim_id: str | None = None

    @field_validator("doc_id", "speaker", "claim_text", "model", mode="before")
    @classmethod
    def _normalize_string_fields(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("claim_type", mode="before")
    @classmethod
    def _normalize_claim_type(cls, value: Any) -> str:
        claim_type = str(value or "other").strip() or "other"
        return claim_type if claim_type in ALLOWED_CLAIM_TYPES else "other"

    @field_validator("boldness_rating", mode="before")
    @classmethod
    def _normalize_boldness(cls, value: Any) -> int:
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            normalized = 2
        if normalized < 1:
            return 1
        if normalized > 3:
            return 3
        return normalized


class QueryRecord(BaseModel):
    """Final normalized validation query row written to JSONL."""

    model_config = ConfigDict(extra="ignore")

    claim_id: str
    query: str
    why_this_query: str
    preferred_sources: list[str] = Field(default_factory=list)

    @field_validator("claim_id", "query", "why_this_query", mode="before")
    @classmethod
    def _normalize_required_text(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("preferred_sources", mode="before")
    @classmethod
    def _normalize_sources(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]
