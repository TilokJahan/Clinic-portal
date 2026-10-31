import re
from dataclasses import dataclass

from pydantic import ValidationError

from app.models import TriageResult, Urgency

# Safety choice: a failed AI call must never silently look "routine", and "urgent" would flood
# the queue. "soon" plus an explicit manual-review message is the cautious middle.
FALLBACK_URGENCY = Urgency.SOON

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


@dataclass
class TriageOutcome:
    result: TriageResult
    fallback_reason: str | None = None  # None means the AI output was valid

    @property
    def is_fallback(self) -> bool:
        return self.fallback_reason is not None


def _fallback(reason: str) -> TriageOutcome:
    return TriageOutcome(
        result=TriageResult(
            urgency=FALLBACK_URGENCY,
            suggested_specialty="General Practice",
            red_flags=[],
            summary="Automatic triage was unavailable. "
            "A clinician should review this intake manually.",
        ),
        fallback_reason=reason,
    )


def parse_llm_output(raw: str) -> TriageOutcome:
    """Parse the model's raw text into a TriageResult, or return a safe fallback.

    Never log `raw` or the validation error text: both can echo the patient's words.
    """
    text = _FENCE.sub("", raw.strip()).strip()  # models often wrap JSON in ```json fences
    try:
        return TriageOutcome(result=TriageResult.model_validate_json(text))
    except ValidationError as exc:
        kinds = {err["type"] for err in exc.errors()}
        return _fallback("invalid_json" if "json_invalid" in kinds else "schema_error")
