from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_metrics_count_triage_and_redacted_entity_types_without_text():
    client.post("/triage", json={"symptoms": "My name is Jane Doe and I have chest pain"})
    text = client.get("/metrics").text
    assert 'triage_requests_total{fallback="none",urgency="urgent"}' in text
    assert 'redacted_entities_total{entity="PERSON"}' in text
    assert "triage_duration_seconds_count" in text
    assert "Jane" not in text and "chest" not in text
