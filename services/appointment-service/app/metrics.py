"""Prometheus metrics for the appointment service, served at GET /metrics.

Labels never contain patient data: only route templates (/triage/{triage_id}), status codes
and urgency levels. /metrics is for Prometheus inside the cluster; nginx doesn't expose it.
"""

import time

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests by route template and status",
    ["method", "route", "status"],
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency by route template", ["method", "route"]
)
BOOKINGS = Counter("appointments_booked_total", "Successful bookings")
BOOKING_CONFLICTS = Counter(
    "appointment_booking_conflicts_total", "Bookings refused with 409", ["reason"]
)
INTAKES = Counter("intakes_total", "Intakes triaged and stored, by AI urgency", ["urgency"])
TRIAGE_CALL_SECONDS = Histogram(
    "triage_service_call_duration_seconds",
    "Time to get an answer from the triage service (includes redaction and the AI)",
    buckets=(0.1, 0.25, 0.5, 1, 2, 4, 8, 15),
)
TRIAGE_FALLBACKS = Counter(
    "triage_fallbacks_total", "Intakes stored with the safe fallback instead of an AI answer"
)
REVIEWS = Counter("triage_reviews_total", "Clinician decisions", ["outcome"])  # accepted/overridden
STREAM_CLIENTS = Gauge("queue_stream_clients", "Open GET /queue/stream connections")

# Create every label value at 0 up front. Otherwise a series only appears on its first event and
# Prometheus' increase()/rate() can't count that first event.
for _urgency in ("routine", "soon", "urgent"):
    INTAKES.labels(_urgency)
for _outcome in ("accepted", "overridden"):
    REVIEWS.labels(_outcome)
for _reason in ("already_booked", "started"):
    BOOKING_CONFLICTS.labels(_reason)


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def record(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        template = getattr(route, "path", "unmatched")  # never the raw path: ids stay out
        if template != "/metrics":
            HTTP_REQUESTS.labels(request.method, template, str(response.status_code)).inc()
            HTTP_LATENCY.labels(request.method, template).observe(time.perf_counter() - started)
        return response

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
