"""AI-written clinician summary and draft patient explanation for flagged lab results.

The model sees only the extracted rows (test, value, unit, reference range, rule flag), never the
report itself, so names, dates of birth and record numbers on the report never reach it. It may
suggest a higher urgency than the rules, never a lower one (see interpret.py). Its patient
explanation is a draft: a clinician approves or edits it before the patient sees anything.
"""

import json
import logging
import os
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ai_client import Generate
from app.labs.rules import FlaggedResult
from app.models import Urgency

logger = logging.getLogger("triage.labs")

SYSTEM_PROMPT = """\
You help a primary-care clinician review a patient's lab results. You provide decision support
only. You do not diagnose, prescribe, or tell the patient what to do beyond contacting the clinic.

You receive the results as JSON. Each has a "flag" computed by fixed clinical rules: normal, low,
high, critical_low, critical_high or unknown. Never contradict these flags. "critical" values
always need urgent attention.

Reply with one JSON object and nothing else:
{
  "clinician_summary": "2-4 sentences for the clinician: which results are abnormal or critical,
    by how much, and any pattern worth noting. Neutral, factual, no diagnosis.",
  "patient_explanation": "3-5 short sentences in plain language (reading age about 12) for the
    patient: what was measured, which results were outside the usual range, and that their care
    team will contact them about next steps. No diagnosis, no medical advice, no alarming wording.
    Do not mention the flags by their technical names.",
  "urgency": "routine | soon | urgent"
}
Choose "urgent" if any result is critical; "soon" if any is low or high; otherwise "routine".
If unsure, choose the more urgent level.
"""


class LabSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clinician_summary: str = Field(min_length=1)
    patient_explanation: str = Field(min_length=1)
    urgency: Urgency


@dataclass
class SummaryReply:
    summary: LabSummary | None  # None = use the rule-based template
    tokens_used: int | None = None
    fallback_reason: str | None = None


def rows_for_model(results: list[FlaggedResult]) -> str:
    return json.dumps(
        [
            {
                "test": r.measurement.display_name,
                "value": r.measurement.value,
                "unit": r.measurement.unit,
                "reference_low": r.measurement.ref_low,
                "reference_high": r.measurement.ref_high,
                "flag": r.flag,
            }
            for r in results
        ],
        indent=1,
    )


def template_summary(results: list[FlaggedResult], reason: str) -> LabSummary:
    """Used when the AI is off or fails: plain, rule-based wording."""
    abnormal = [r for r in results if r.flag not in ("normal", "unknown")]
    return LabSummary(
        clinician_summary=(
            f"{reason}. {len(results)} result(s) read, {len(abnormal)} outside the range."
        ),
        patient_explanation=(
            "We received your lab results. "
            + (
                "Some results are outside the usual range. "
                if abnormal
                else "Your results are within the usual range. "
            )
            + "Your care team will review them and contact you about next steps."
        ),
        urgency=Urgency.ROUTINE,
    )


class FakeLabSummarizer:
    """No AI: the template. Local development and tests."""

    def summarize(self, results: list[FlaggedResult]) -> SummaryReply:
        return SummaryReply(None)


class AILabSummarizer:
    def __init__(self, generate: Generate):
        self._generate = generate

    @classmethod
    def from_env(cls) -> "AILabSummarizer":
        from app.ai_client import azure_openai_generate

        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
        if not endpoint:
            raise ValueError("TRIAGE_CLIENT=azure-openai needs AZURE_OPENAI_ENDPOINT")
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini").strip()
        return cls(azure_openai_generate(endpoint, deployment))

    def summarize(self, results: list[FlaggedResult]) -> SummaryReply:
        if not results:
            return SummaryReply(None, None, "no_results")
        try:
            reply = self._generate(SYSTEM_PROMPT, "Lab results:\n" + rows_for_model(results))
        except Exception as exc:  # never fail the report because of the AI
            logger.warning("lab summary AI call failed (%s), using template", type(exc).__name__)
            return SummaryReply(None, None, "model_error")
        try:
            return SummaryReply(LabSummary.model_validate_json(reply.text), reply.tokens_used)
        except ValidationError:
            logger.warning("lab summary AI reply rejected, using template")
            return SummaryReply(None, reply.tokens_used, "schema_error")


def get_summarizer():
    if os.getenv("TRIAGE_CLIENT", "fake").strip().lower() == "azure-openai":
        return AILabSummarizer.from_env()
    return FakeLabSummarizer()
