"""Booking requests: the patient describes their symptoms, a clinician approves or declines."""

import pytest

from app.triage import get_triage_client
from tests.conftest import DB_DIR, as_user
from tests.test_intake_queue import FakeTriage

PATIENT = as_user(1)
OTHER = as_user(2)
CLINICIAN = as_user(3, role="clinician", email="doc@example.com")


@pytest.fixture
def world(client, db):
    from app.main import app

    db.execute("INSERT INTO providers (name, specialty) VALUES ('Dr. One', 'General Practice')")
    db.execute(
        "INSERT INTO users (email, role) VALUES ('p1@example.com', 'patient'), "
        "('p2@example.com', 'patient'), ('doc@example.com', 'clinician')"
    )
    db.execute(
        """
        INSERT INTO slots (provider_id, starts_at, ends_at) VALUES
            (1, now() + interval '3 days', now() + interval '3 days 30 minutes'),
            (1, now() + interval '1 day', now() + interval '1 day 30 minutes')
        """
    )
    fake = FakeTriage()
    app.dependency_overrides[get_triage_client] = lambda: fake
    db.triage = fake
    return db


def _request(client, symptoms: str | None = "a sore throat", slot: int = 1, who=PATIENT):
    body = {"slot_id": slot} | ({"symptoms": symptoms} if symptoms is not None else {})
    return client.post("/appointments", json=body, headers=who)


def _mine(client, who=PATIENT):
    return client.get("/appointments", headers=who).json()


def _entry(client):
    [entry] = client.get("/queue", headers=CLINICIAN).json()
    return entry


def test_a_request_with_symptoms_holds_the_slot_and_waits_for_approval(client, world):
    response = _request(client, "crushing chest pain")
    assert response.status_code == 201
    assert response.json()["approved_at"] is None
    assert world.triage.calls == ["crushing chest pain"]
    entry = _entry(client)
    assert entry["awaiting_approval"] is True
    assert entry["triage"]["urgency"] == "urgent"
    [mine] = _mine(client)
    assert mine["approved"] is False and mine["intake_submitted"] is True
    # The slot is held: nobody else can request it
    assert _request(client, slot=1, who=OTHER).status_code == 409
    # The symptom text itself is never stored
    rows = world.execute("SELECT * FROM triage_results").fetchall()
    assert "crushing" not in str(rows)


def test_approving_needs_the_symptoms_first(client, world):
    _request(client, symptoms=None)
    response = client.post("/appointments/1/approve", headers=CLINICIAN)
    assert response.status_code == 409
    assert response.json()["detail"] == "The patient hasn't described their symptoms yet"
    intake = {"appointment_id": 1, "symptoms": "cough"}
    assert client.post("/intake", json=intake, headers=PATIENT).status_code == 201
    response = client.post("/appointments/1/approve", headers=CLINICIAN)
    assert response.status_code == 200 and response.json()["approved_at"] is not None
    assert _mine(client)[0]["approved"] is True
    assert _entry(client)["awaiting_approval"] is False
    approver = world.execute("SELECT approved_by FROM appointments WHERE id = 1").fetchone()
    assert approver[0] == 3


def test_approve_is_for_clinicians_and_only_once(client, world):
    _request(client)
    assert client.post("/appointments/1/approve", headers=PATIENT).status_code == 403
    assert client.post("/appointments/99/approve", headers=CLINICIAN).status_code == 404
    assert client.post("/appointments/1/approve", headers=CLINICIAN).status_code == 200
    again = client.post("/appointments/1/approve", headers=CLINICIAN)
    assert again.status_code == 409 and again.json()["detail"] == "Already approved"
    assert client.post("/appointments/1/decline", json={}, headers=CLINICIAN).status_code == 409


def test_declining_frees_the_slot_and_tells_the_patient_why(client, world):
    _request(client)
    response = client.post(
        "/appointments/1/decline",
        json={"reason": "  Please book with your own doctor.  "},
        headers=CLINICIAN,
    )
    assert response.status_code == 200 and response.json()["status"] == "cancelled"
    [mine] = _mine(client)
    assert mine["declined"] is True and mine["status"] == "cancelled"
    assert mine["decline_reason"] == "Please book with your own doctor."
    assert client.get("/queue", headers=CLINICIAN).json() == []
    # The slot is free again
    assert _request(client, slot=1, who=OTHER).status_code == 201
    # Once the requested time has passed, the declined request is no longer listed
    world.execute("UPDATE slots SET starts_at = now() - interval '1 hour' WHERE id = 1")
    assert _mine(client) == []


def test_declining_expires_an_offered_time(client, world):
    _request(client)
    offer = client.post(
        "/appointments/1/reschedule-offers", json={"slot_id": 2}, headers=CLINICIAN
    ).json()
    assert client.post("/appointments/1/decline", json={}, headers=CLINICIAN).status_code == 200
    status = world.execute("SELECT status FROM reschedule_offers WHERE id = %s", (offer["id"],))
    assert status.fetchone()[0] == "expired"


def test_accepting_a_clinicians_offer_counts_as_approved(client, world):
    _request(client)
    offer = client.post(
        "/appointments/1/reschedule-offers", json={"slot_id": 2}, headers=CLINICIAN
    ).json()
    moved = client.post(f"/reschedule-offers/{offer['id']}/accept", headers=PATIENT).json()
    assert moved["approved"] is True and moved["slot_id"] == 2


def test_the_migration_approves_existing_bookings_once(client, world):
    _request(client)
    migration = (DB_DIR / "schemav7_approval.sql").read_text()
    # Run again on a database that already has the columns: the waiting request stays waiting
    world.execute(migration)
    assert _mine(client)[0]["approved"] is False
    # On a database from before approval existed, existing bookings count as approved
    world.execute(
        "ALTER TABLE appointments DROP COLUMN approved_at, DROP COLUMN approved_by, "
        "DROP COLUMN declined_at, DROP COLUMN decline_reason"
    )
    world.execute(migration)
    assert _mine(client)[0]["approved"] is True
