"""Domain models for extracted predictions."""

from pydantic import BaseModel, Field


class Prediction(BaseModel):
    """Structured representation of one extracted prediction."""

    source_id: str = Field(description="ID of the transcript or segment source.")
    text: str = Field(description="Raw prediction text.")
    speaker: str | None = Field(default=None, description="Optional speaker name.")
