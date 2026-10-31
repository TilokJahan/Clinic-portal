from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Urgency(StrEnum):
    ROUTINE = "routine"
    SOON = "soon"
    URGENT = "urgent"


class TriageRequest(BaseModel):
    symptoms: str = Field(min_length=1, max_length=4000)


class TriageResult(BaseModel):
    """Structured output we require from the LLM. Validate every AI response against this."""

    model_config = ConfigDict(extra="forbid")  # reject fields we did not ask for

    urgency: Urgency
    suggested_specialty: str = Field(min_length=1)
    red_flags: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)


class TriageResponse(BaseModel):
    """What POST /triage returns: the validated result plus metadata about the AI call."""

    urgency: Urgency
    suggested_specialty: str
    red_flags: list[str]
    summary: str
    tokens_used: int | None = None
    # True when the model failed or answered badly and the safe fallback was used
    fallback: bool = False
