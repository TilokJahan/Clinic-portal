import logging
import time

from fastapi import FastAPI, HTTPException, Request

from app import metrics
from app.ai_client import ClientReply
from app.labs.extract import IMAGES, PDF, Extractor, get_extractor
from app.labs.interpret import LabInterpretation, interpret
from app.labs.summary import get_summarizer
from app.models import TriageRequest, TriageResponse, Urgency
from app.red_flags import find_red_flags
from app.redaction import redact
from app.triage_client import TriageClient, get_client

# Log only metadata (entity types, timings). Never log symptom text, before or after redaction.
logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s %(message)s")
logger = logging.getLogger("triage")

app = FastAPI(title="Triage Service", version="0.1.0")
metrics.install(app)

client: TriageClient = get_client()
lab_extractor: Extractor = get_extractor()
lab_summarizer = get_summarizer()

MAX_LAB_BYTES = 10 * 1024 * 1024
LAB_TYPES = {PDF, *IMAGES}


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
    # Fixed red-flag rules: any match is urgent, whatever the AI said (it can't lower a rule)
    rule_flags = find_red_flags(redacted.text)
    if rule_flags:
        result = reply.result
        reply.result = result.model_copy(
            update={
                "urgency": Urgency.URGENT,
                "red_flags": list(dict.fromkeys([*rule_flags, *result.red_flags])),
            }
        )
        metrics.RULE_RED_FLAGS.labels(
            "raised" if result.urgency != Urgency.URGENT else "agreed"
        ).inc()
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
        "triage done urgency=%s rule_flags=%d redacted_entities=%s fallback=%s tokens=%s "
        "duration_ms=%d",
        reply.result.urgency,
        len(rule_flags),
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


@app.post("/labs/interpret")
async def interpret_lab_report(request: Request) -> LabInterpretation:
    """Internal (called by the appointment service). Body: the report file; Content-Type: its type.

    The report itself never leaves this service except to the OCR service, and only the extracted
    rows go to the AI. Nothing is stored here.
    """
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in LAB_TYPES:
        raise HTTPException(415, "Send a PDF, PNG or JPEG")
    body = await request.body()
    if not body or len(body) > MAX_LAB_BYTES:
        raise HTTPException(413, "The report must be between 1 byte and 10 MB")
    return interpret(body, content_type, lab_extractor, lab_summarizer)
