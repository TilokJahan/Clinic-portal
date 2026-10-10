from fastapi import FastAPI

app = FastAPI(title="Appointment Service", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check used by docker-compose, Kubernetes probes, and CI."""
    return {"status": "ok", "service": "appointment-service"}


# TODO (Backend A): slots, booking, queue, SSE stream. See docs/api.md for the contract.
