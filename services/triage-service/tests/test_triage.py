import logging

from fastapi.testclient import TestClient

from app import main
from app.main import app
from app.models import TriageResult, Urgency

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok", "service": "triage-service"}


def test_routine_symptoms():
    response = client.post("/triage", json={"symptoms": "mild sore throat for two days"})
    assert response.status_code == 200
    assert response.json()["urgency"] == "routine"


def test_red_flag_symptoms_are_urgent():
    response = client.post("/triage", json={"symptoms": "I have chest pain and feel dizzy"})
    assert response.status_code == 200
    assert response.json()["urgency"] == "urgent"


def test_empty_symptoms_rejected():
    response = client.post("/triage", json={"symptoms": ""})
    assert response.status_code == 422


class RecordingClient:
    """Stands in for the AI client and remembers exactly what text it was given."""

    def __init__(self):
        self.received: list[str] = []

    def triage(self, redacted_text: str) -> TriageResult:
        self.received.append(redacted_text)
        return TriageResult(
            urgency=Urgency.URGENT, suggested_specialty="Emergency Medicine", summary="test"
        )


def test_client_receives_redacted_text_not_the_original(monkeypatch):
    recorder = RecordingClient()
    monkeypatch.setattr(main, "client", recorder)
    response = client.post(
        "/triage", json={"symptoms": "My name is Jane Doe, call me at 555-123-4567, chest pain"}
    )
    assert response.status_code == 200
    [sent] = recorder.received
    assert "Jane" not in sent and "Doe" not in sent
    assert "555-123-4567" not in sent
    assert "chest pain" in sent
    assert "<PERSON>" in sent and "<PHONE_NUMBER>" in sent


def test_symptom_text_is_never_logged(caplog):
    secret = "My name is Jane Doe, call me at 555-123-4567, chest pain"
    with caplog.at_level(logging.DEBUG):
        client.post("/triage", json={"symptoms": secret})
    logged = caplog.text
    assert "triage done" in logged
    for fragment in ("Jane", "Doe", "555-123-4567", "chest pain"):
        assert fragment not in logged
