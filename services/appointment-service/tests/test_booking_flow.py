"""Booking with symptoms first: assess, then request a time the urgency allows."""

from datetime import UTC, datetime, timedelta

import pytest

from app.triage import get_triage_client
from tests.conftest import as_user
from tests.test_intake_queue import FakeTriage

PATIENT = as_user(1)
OTHER = as_user(2)
CLINICIAN = as_user(3, role="clinician", email="doc@example.com")
IN_5H, IN_2D, IN_10D = 1, 2, 3


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
            (1, now() + interval '5 hours', now() + interval '5 hours 30 minutes'),
            (1, now() + interval '2 days', now() + interval '2 days 30 minutes'),
            (1, now() + interval '10 days', now() + interval '10 days 30 minutes')
        """
    )
    app.dependency_overrides[get_triage_client] = FakeTriage
    return db


def _assess(client, symptoms="a mild rash", who=PATIENT):
    return client.post("/assessments", json={"symptoms": symptoms}, headers=who)


def _request(client, slot, assessment_id, who=PATIENT):
    body = {"slot_id": slot, "assessment_id": assessment_id}
    return client.post("/appointments", json=body, headers=who)


def test_an_assessment_comes_first_and_sets_the_limit(client, world):
    response = _assess(client, "crushing chest pain")
    assert response.status_code == 201
    body = response.json()
    assert body["triage"]["urgency"] == "urgent" and body["triage"]["appointment_id"] is None
    assert body["max_within_hours"] == 24
    assert _assess(client).json()["max_within_hours"] == 14 * 24
    # Nothing reaches the clinician before a time is requested
    assert client.get("/queue", headers=CLINICIAN).json() == []


def test_an_urgent_patient_cannot_request_a_time_past_the_limit(client, world):
    assessment = _assess(client, "crushing chest pain").json()["triage"]["id"]
    response = _request(client, IN_10D, assessment)
    assert response.status_code == 422
    assert "within 24 hours" in response.json()["detail"]
    assert _request(client, IN_5H, assessment).status_code == 201
    [entry] = client.get("/queue", headers=CLINICIAN).json()
    assert entry["triage"]["urgency"] == "urgent" and entry["awaiting_approval"] is True


def test_a_later_time_is_allowed_when_nothing_is_free_in_time(client, world):
    world.execute("INSERT INTO appointments (patient_id, slot_id) VALUES (2, %s)", (IN_5H,))
    assessment = _assess(client, "crushing chest pain").json()["triage"]["id"]
    assert _request(client, IN_2D, assessment).status_code == 201


def test_an_assessment_is_used_once_and_only_by_its_patient(client, world):
    assessment = _assess(client).json()["triage"]["id"]
    assert _request(client, IN_2D, assessment, who=OTHER).status_code == 404
    assert _request(client, IN_2D, assessment).status_code == 201
    assert _request(client, IN_10D, assessment).status_code == 404
    world.execute("UPDATE triage_results SET created_at = now() - interval '2 days'")
    stale = _assess(client).json()["triage"]["id"]
    world.execute(
        "UPDATE triage_results SET created_at = now() - interval '2 days' WHERE id = %s", (stale,)
    )
    response = _request(client, IN_10D, stale)
    assert response.status_code == 409
    assert response.json()["detail"] == "Please describe your symptoms again"


def test_a_day_can_be_listed_with_booked_times_greyed_out(client, world):
    world.execute("INSERT INTO appointments (patient_id, slot_id) VALUES (2, %s)", (IN_2D,))
    day = (datetime.now(UTC) + timedelta(days=2)).date().isoformat()
    free_only = client.get("/slots", params={"date": day}, headers=PATIENT).json()
    whole_day = client.get(
        "/slots", params={"date": day, "include_booked": "true"}, headers=PATIENT
    ).json()
    assert IN_2D not in [s["id"] for s in free_only]
    [booked] = [s for s in whole_day if s["id"] == IN_2D]
    assert booked["available"] is False


def test_timeframes_report_free_times_and_what_the_priority_allows(client, world):
    def frames(**params):
        response = client.get("/slots/timeframes", params=params, headers=PATIENT)
        assert response.status_code == 200
        return {f["hours"]: (f["free"], f["allowed"]) for f in response.json()}

    assert frames() == {24: (1, True), 72: (2, True), 168: (2, True), 336: (3, True)}
    world.execute("INSERT INTO appointments (patient_id, slot_id) VALUES (2, %s)", (IN_5H,))
    urgent = frames(priority="urgent")
    assert urgent[24] == (0, True) and urgent[72] == (1, False)
