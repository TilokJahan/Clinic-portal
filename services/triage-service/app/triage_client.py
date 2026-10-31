import os
from typing import Protocol

from app.ai_client import ClientReply
from app.models import TriageResult, Urgency


class TriageClient(Protocol):
    """Anything that turns (already redacted) symptom text into a TriageResult.

    Build against this interface so the team can work without cloud access.
    FakeTriageClient is the default; AITriageClient (Azure OpenAI) is chosen with TRIAGE_CLIENT.
    """

    def triage(self, redacted_text: str) -> "TriageResult | ClientReply": ...


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


def get_client() -> TriageClient:
    """Pick the triage client from the TRIAGE_CLIENT environment variable."""
    name = os.getenv("TRIAGE_CLIENT", "fake").strip().lower()
    if name == "fake":
        return FakeTriageClient()
    if name == "azure-openai":
        from app.ai_client import AITriageClient

        return AITriageClient.from_env()
    raise ValueError(f"Unknown TRIAGE_CLIENT {name!r}. Use 'fake' or 'azure-openai'.")
