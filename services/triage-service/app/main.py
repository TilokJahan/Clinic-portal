from fastapi import FastAPI

from app.models import TriageRequest, TriageResult
from app.triage_client import TriageClient, get_client

app = FastAPI(title="Triage Service", version="0.1.0")

client: TriageClient = get_client()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "triage-service"}


@app.post("/triage", response_model=TriageResult)
def triage(request: TriageRequest) -> TriageResult:
    # TODO (Backend B): redact PII with Presidio BEFORE this call, then store the result.
    return client.triage(request.symptoms)
