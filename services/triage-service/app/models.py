from enum import StrEnum

from pydantic import BaseModel, Field


class Urgency(StrEnum):
    ROUTINE = "routine"
    SOON = "soon"
    URGENT = "urgent"


class TriageRequest(BaseModel):
    symptoms: str = Field(min_length=1, max_length=4000)


class TriageResult(BaseModel):
    """Structured output we require from the LLM. Validate every AI response against this."""

    urgency: Urgency
    suggested_specialty: str
    red_flags: list[str] = []
    summary: str
