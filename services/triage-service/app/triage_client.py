from typing import Protocol

from app.models import TriageResult, Urgency


class TriageClient(Protocol):
    """Anything that turns (already redacted) symptom text into a TriageResult.

    Build against this interface so the team can work without cloud access.
    Later, add a GeminiTriageClient that calls Vertex AI and swap it in via TRIAGE_CLIENT.
    """

    def triage(self, redacted_text: str) -> TriageResult: ...


class FakeTriageClient:
    """Canned results for local development and tests. No network, no cost."""

    def triage(self, redacted_text: str) -> TriageResult:
        text = redacted_text.lower()
        if any(word in text for word in ("chest pain", "can't breathe", "unconscious")):
            return TriageResult(
                urgency=Urgency.URGENT,
                suggested_specialty="Emergency Medicine",
                red_flags=["possible cardiac or respiratory emergency"],
                summary="Potentially serious symptom reported. Clinician review needed now.",
            )
        return TriageResult(
            urgency=Urgency.ROUTINE,
            suggested_specialty="General Practice",
            red_flags=[],
            summary="No red-flag symptoms detected in the intake text.",
        )
