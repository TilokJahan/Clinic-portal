from concurrent.futures import ThreadPoolExecutor

import pytest


@pytest.fixture
def data(db):
    """Two providers, three slots on 2030-01-07 plus one the next day, two patients."""
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
            (1, '2030-01-08 09:00+00', '2030-01-08 09:30+00')
        """
    )
    return {"patient": 1, "other_patient": 2, "clinician": 3}


def _book(client, patient_id: int, slot_id: int):
    return client.post("/appointments", json={"patient_id": patient_id, "slot_id": slot_id})


def test_slots_for_a_day(client, data):
    response = client.get("/slots", params={"date": "2030-01-07"})
    assert response.status_code == 200
    slots = response.json()
    assert [s["id"] for s in slots] == [1, 3, 2]
    assert slots[0] == {
        "id": 1,
        "provider_id": 1,
        "starts_at": "2030-01-07T09:00:00Z",
        "ends_at": "2030-01-07T09:30:00Z",
    }


def test_slots_filtered_by_provider(client, data):
    response = client.get("/slots", params={"date": "2030-01-07", "provider_id": 2})
    assert [s["id"] for s in response.json()] == [3]


def test_booked_slots_are_hidden(client, data):
    assert _book(client, data["patient"], 1).status_code == 201
    response = client.get("/slots", params={"date": "2030-01-07"})
    assert [s["id"] for s in response.json()] == [3, 2]


@pytest.mark.parametrize(
    "params",
    [{}, {"date": "07-01-2030"}, {"date": "2030-01-07", "provider_id": 0}],
    ids=["missing-date", "bad-date", "bad-provider"],
)
def test_slots_rejects_bad_query(client, params):
    assert client.get("/slots", params=params).status_code == 422


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


def test_concurrent_bookings_only_one_wins(client, data):
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = sorted(pool.map(lambda patient: _book(client, patient, 1).status_code, [1, 2]))
    assert codes == [201, 409]


@pytest.mark.parametrize(
    ("patient", "slot", "detail"),
    [(1, 999, "Slot not found"), (999, 1, "Patient not found"), (3, 1, "Patient not found")],
    ids=["unknown-slot", "unknown-patient", "not-a-patient"],
)
def test_book_unknown_slot_or_patient_returns_404(client, data, patient, slot, detail):
    response = _book(client, patient, slot)
    assert response.status_code == 404
    assert response.json() == {"detail": detail}


def test_book_rejects_invalid_body(client):
    assert client.post("/appointments", json={"slot_id": 1}).status_code == 422
