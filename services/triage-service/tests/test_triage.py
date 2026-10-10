from fastapi.testclient import TestClient

from app.main import app

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
