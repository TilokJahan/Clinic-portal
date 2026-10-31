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
LAB_REPORTS = Counter(
    "lab_reports_total",
    "Lab reports interpreted, by outcome and lab urgency",
    ["status", "urgency"],
)
LAB_RESULTS = Counter("lab_results_total", "Lab results read, by rule flag", ["flag"])
LAB_CONFIDENCE = Histogram(
    "lab_extraction_confidence",
    "Lowest OCR confidence per report (extraction accuracy proxy)",
    buckets=(0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.98, 1.0),
)
LAB_SECONDS = Histogram(
    "lab_interpret_duration_seconds",
    "OCR + rules + AI summary per report",
    buckets=(0.5, 1, 2, 4, 8, 15, 30, 60),
)

# Create the common label values at 0 up front, so increase()/rate() also count the first event.
for _urgency in ("routine", "soon", "urgent"):
    TRIAGE_REQUESTS.labels(_urgency, "none")
for _entity in ("PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS", "LOCATION", "US_SSN"):
    REDACTED_ENTITIES.labels(_entity)
for _flag in ("normal", "low", "high", "critical_low", "critical_high", "unknown"):
    LAB_RESULTS.labels(_flag)
for _status in ("ready", "needs_review"):
    for _urgency in ("routine", "soon", "urgent"):
        LAB_REPORTS.labels(_status, _urgency)


def install(app: FastAPI) -> None:
    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
