import logging
import os
import time

import httpx
from pydantic import ValidationError

from app.models import TriageAssessment, Urgency

logger = logging.getLogger("appointment.triage")

# Same cautious default as the triage service's own parser: never silently "routine".
FALLBACK = TriageAssessment(
    urgency=Urgency.SOON,
    suggested_specialty="General Practice",
    red_flags=[],
    summary="Automatic triage was unavailable. A clinician should review this intake manually.",
    fallback=True,
)


class TriageServiceClient:
    """Calls the triage service's POST /triage. Never logs the symptom text."""

    def __init__(self, base_url: str, timeout: float = 15.0, transport=None):
        self._http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def assess(self, symptoms: str) -> tuple[TriageAssessment, int]:
        """Return the assessment and how long it took in ms. Falls back if the call fails."""
        started = time.perf_counter()
        try:
            response = self._http.post("/triage", json={"symptoms": symptoms})
            response.raise_for_status()
            assessment = TriageAssessment.model_validate(response.json())
        except (httpx.HTTPError, ValueError, ValidationError) as exc:
            logger.warning("triage service call failed (%s), using fallback", type(exc).__name__)
            assessment = FALLBACK
        return assessment, round((time.perf_counter() - started) * 1000)


_client: TriageServiceClient | None = None


def get_triage_client() -> TriageServiceClient:
    """FastAPI dependency. The URL comes from TRIAGE_SERVICE_URL."""
    global _client
    if _client is None:
        _client = TriageServiceClient(
            os.environ.get("TRIAGE_SERVICE_URL", "http://triage-service:8000")
        )
    return _client
