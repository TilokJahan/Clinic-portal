"""Prometheus metrics for the triage service, served at GET /metrics.

Labels hold only urgency levels, entity types and fallback reasons, never symptom text.
"""

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

TRIAGE_REQUESTS = Counter(
    "triage_requests_total",
    "Triage results by urgency and fallback reason",
    ["urgency", "fallback"],
)
TRIAGE_SECONDS = Histogram(
    "triage_duration_seconds",
    "Redaction plus AI call",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 15),
)
REDACTED_ENTITIES = Counter(
    "redacted_entities_total",
    "Requests in which this kind of personal detail was removed",
    ["entity"],
)
LLM_TOKENS = Counter("llm_tokens_total", "Tokens used by the AI model (input + output)")

# Create the common label values at 0 up front, so increase()/rate() also count the first event.
for _urgency in ("routine", "soon", "urgent"):
    TRIAGE_REQUESTS.labels(_urgency, "none")
for _entity in ("PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS", "LOCATION", "US_SSN"):
    REDACTED_ENTITIES.labels(_entity)


def install(app: FastAPI) -> None:
    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
