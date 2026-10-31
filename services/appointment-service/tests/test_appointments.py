from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.conftest import as_user


@pytest.fixture
def data(db):
    """Two providers, three slots on 2030-01-07, one the next day, one in the past, two patients."""
    db.execute(
        "INSERT INTO providers (name, specialty) VALUES "
        "('Dr. One', 'General Practice'), ('Dr. Two', 'Dermatology')"
    )
    db.execute(
        "INSERT INTO users (email, role) VALUES "
        "('p1@example.com', 'patient'), ('p2@example.com', 'patient'), "
        "('doc@example.com', 'clinician')"
    )
    db.execute(
        """
        INSERT INTO slots (provider_id, starts_at, ends_at) VALUES
            (1, '2030-01-07 09:00+00', '2030-01-07 09:30+00'),
            (1, '2030-01-07 09:30+00', '2030-01-07 10:00+00'),
            (2, '2030-01-07 09:00+00', '2030-01-07 09:30+00'),
            (1, '2030-01-08 09:00+00', '2030-01-08 09:30+00'),
            (1, '2020-01-06 09:00+00', '2020-01-06 09:30+00')
        """
    )
    return {"patient": 1, "other_patient": 2, "clinician": 3}


def _book(client, patient_id: int, slot_id: int):
    return client.post("/appointments", json={"slot_id": slot_id}, headers=as_user(patient_id))


def _slots(client, **params):
    return client.get("/slots", params=params, headers=as_user(1))


def test_slots_for_a_day(client, data):
    response = _slots(client, date="2030-01-07")
    assert response.status_code == 200
    slots = response.json()
    assert [s["id"] for s in slots] == [1, 3, 2]
    assert slots[0] == {
        "id": 1,
        "provider_id": 1,
        "provider_name": "Dr. One",
        "specialty": "General Practice",
        "starts_at": "2030-01-07T09:00:00Z",
        "ends_at": "2030-01-07T09:30:00Z",
    }


def test_slots_filtered_by_provider(client, data):
    response = _slots(client, date="2030-01-07", provider_id=2)
    assert [s["id"] for s in response.json()] == [3]


def test_booked_slots_are_hidden(client, data):
    assert _book(client, data["patient"], 1).status_code == 201
    response = _slots(client, date="2030-01-07")
    assert [s["id"] for s in response.json()] == [3, 2]


def test_past_slots_are_hidden(client, data):
    assert _slots(client, date="2020-01-06").json() == []


def test_cancelled_slot_is_listed_and_bookable_again(client, data, db):
    assert _book(client, data["patient"], 1).status_code == 201
    db.execute("UPDATE appointments SET status = 'cancelled' WHERE slot_id = 1")
    response = _slots(client, date="2030-01-07")
    assert [s["id"] for s in response.json()] == [1, 3, 2]
    assert _book(client, data["other_patient"], 1).status_code == 201
    assert _book(client, data["patient"], 1).status_code == 409


@pytest.mark.parametrize(
    "params",
    [{}, {"date": "07-01-2030"}, {"date": "2030-01-07", "provider_id": 0}],
    ids=["missing-date", "bad-date", "bad-provider"],
)
def test_slots_rejects_bad_query(client, params):
    assert client.get("/slots", params=params, headers=as_user(1)).status_code == 422


def test_book_a_slot(client, data):
    response = _book(client, data["patient"], 2)
    assert response.status_code == 201
    body = response.json()
    assert body["patient_id"] == data["patient"]
    assert body["slot_id"] == 2
    assert body["status"] == "booked"
    assert body["id"] > 0 and body["created_at"]


def test_booking_the_same_slot_twice_returns_409(client, data):
    assert _book(client, data["patient"], 1).status_code == 201
    response = _book(client, data["other_patient"], 1)
    assert response.status_code == 409
    assert response.json() == {"detail": "Slot is already booked"}


def test_booking_a_past_slot_returns_409(client, data):
    response = _book(client, data["patient"], 5)
    assert response.status_code == 409
    assert response.json() == {"detail": "Slot has already started"}


def test_concurrent_bookings_only_one_wins(client, data):
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(pool.map(lambda patient: _book(client, patient, 1).status_code, [1, 2]))
    assert codes == [201, 409]


def test_book_unknown_slot_returns_404(client, data):
    response = _book(client, data["patient"], 999)
    assert response.status_code == 404
    assert response.json() == {"detail": "Slot not found"}


def test_booking_needs_a_signed_in_patient(client, data):
    assert client.post("/appointments", json={"slot_id": 1}).status_code == 401
    clinician = as_user(data["clinician"], role="clinician")
    assert client.post("/appointments", json={"slot_id": 1}, headers=clinician).status_code == 403


def test_token_for_a_user_that_no_longer_exists_returns_401(client, data):
    response = _book(client, 999, 1)
    assert response.status_code == 401


def test_patient_id_in_the_body_is_ignored(client, data):
    response = client.post(
        "/appointments", json={"slot_id": 2, "patient_id": 2}, headers=as_user(data["patient"])
    )
    assert response.status_code == 201
    assert response.json()["patient_id"] == data["patient"]


def test_book_rejects_invalid_body(client):
    assert client.post("/appointments", json={}, headers=as_user(1)).status_code == 422


def test_ready_checks_the_database(client):
    assert client.get("/ready").json() == {"status": "ready"}


def test_cors_allows_only_listed_origins(monkeypatch):
    import importlib

    from fastapi.testclient import TestClient

    import app.main

    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://clinic.example.org")
    module = importlib.reload(app.main)
    try:
        cors = TestClient(module.app)
        preflight = {"Access-Control-Request-Method": "GET"}
        ok = cors.options("/slots", headers={"Origin": "https://clinic.example.org", **preflight})
        assert ok.headers["access-control-allow-origin"] == "https://clinic.example.org"
        bad = cors.options("/slots", headers={"Origin": "https://evil.example.com", **preflight})
        assert "access-control-allow-origin" not in bad.headers
    finally:
        monkeypatch.delenv("CORS_ALLOWED_ORIGINS")
        importlib.reload(app.main)
