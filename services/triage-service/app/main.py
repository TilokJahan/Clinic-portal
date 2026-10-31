import logging
import time

from fastapi import FastAPI

from app import metrics
from app.gemini_client import ClientReply
from app.models import TriageRequest, TriageResponse
from app.redaction import redact
from app.triage_client import TriageClient, get_client

# Log only metadata (entity types, timings). Never log symptom text, before or after redaction.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s %(message)s")
logger = logging.getLogger("triage")

app = FastAPI(title="Triage Service", version="0.1.0")
metrics.install(app)

client: TriageClient = get_client()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "triage-service"}


@app.post("/triage")
def triage(request: TriageRequest) -> TriageResponse:
    """Redact private details, then ask the triage client. The client never sees the original."""
    started = time.perf_counter()
    redacted = redact(request.symptoms)
    reply = client.triage(redacted.text)
    if not isinstance(reply, ClientReply):  # simple clients (fake, tests) return a bare result
        reply = ClientReply(reply)
    elapsed = time.perf_counter() - started
    metrics.TRIAGE_SECONDS.observe(elapsed)
    metrics.TRIAGE_REQUESTS.labels(
        reply.result.urgency.value, reply.fallback_reason or "none"
    ).inc()
    for entity in redacted.entities:
        metrics.REDACTED_ENTITIES.labels(entity).inc()
    if reply.tokens_used:
        metrics.LLM_TOKENS.inc(reply.tokens_used)
    logger.info(
        "triage done urgency=%s redacted_entities=%s fallback=%s tokens=%s duration_ms=%d",
        reply.result.urgency,
        ",".join(redacted.entities) or "none",
        reply.fallback_reason or "no",
        reply.tokens_used,
        elapsed * 1000,
    )
    return TriageResponse(
        **reply.result.model_dump(),
        tokens_used=reply.tokens_used,
        fallback=reply.fallback_reason is not None,
    )
