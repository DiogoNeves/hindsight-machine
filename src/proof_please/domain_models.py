"""Domain models for extracted health claims."""

from pydantic import BaseModel, Field


class HealthClaim(BaseModel):
    """Structured representation of one extracted health claim."""

    source_id: str = Field(description="ID of the transcript or segment source.")
    claim_text: str = Field(description="Raw health claim text.")
    speaker: str | None = Field(default=None, description="Optional speaker name.")
