import logging
import time

from fastapi import FastAPI

from app.models import TriageRequest, TriageResult
from app.redaction import redact
from app.triage_client import TriageClient, get_client

# Log only metadata (entity types, timings). Never log symptom text, before or after redaction.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s %(message)s")
logger = logging.getLogger("triage")

app = FastAPI(title="Triage Service", version="0.1.0")

client: TriageClient = get_client()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "triage-service"}


@app.post("/triage", response_model=TriageResult)
def triage(request: TriageRequest) -> TriageResult:
    """Redact private details, then ask the triage client. The client never sees the original."""
    started = time.perf_counter()
    redacted = redact(request.symptoms)
    result = client.triage(redacted.text)
    logger.info(
        "triage done urgency=%s redacted_entities=%s duration_ms=%d",
        result.urgency,
        ",".join(redacted.entities) or "none",
        (time.perf_counter() - started) * 1000,
    )
    return result
