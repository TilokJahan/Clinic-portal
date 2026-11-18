# ruff: noqa: F811  (pytest fixtures imported from other test modules)
"""Lab visits: the lab proposes times for a requested test; the patient accepts or chooses."""

from datetime import UTC, datetime, timedelta

import pytest

from app.lab_visits import _candidates
from tests.test_labs import lab_setup  # noqa: F401  (fixture)
from tests.test_roles_labs import (  # noqa: F401
    CLINICIAN,
    LAB_TECH,
    OTHER,
    PATIENT,
    PHYSICIAN,
    world,
)


@pytest.fixture
def request_id(client, world):  # noqa: F811
    """A routine ultrasound requested for patient 1's visit (routine: within two weeks, so there
    are always lab times in the window whatever day the tests run)."""
    response = client.post(
        "/appointments/1/lab-requests",
        json={"exam_type": "ultrasound", "urgency": "routine", "note": "Abdomen"},
        headers=CLINICIAN,
    )
    assert response.status_code == 201
    return response.json()["id"]


def _times(client, request_id, headers=LAB_TECH):
    url = (
        f"/lab/requests/{request_id}/times"
        if headers == LAB_TECH
        else f"/lab-requests/{request_id}/times"
    )
    response = client.get(url, headers=headers)
    assert response.status_code == 200
    return response.json()


def _propose(client, request_id, times):
    return client.post(
        f"/lab/requests/{request_id}/propose", json={"times": times}, headers=LAB_TECH
    )


def _schedule(client, request_id, at, headers=PATIENT):
    return client.post(
        f"/lab-requests/{request_id}/schedule", json={"starts_at": at}, headers=headers
    )


def _mine(client):
    [visit] = client.get("/appointments", headers=PATIENT).json()
    [request] = visit["lab_requests"]
    return request


def test_the_lab_proposes_times_and_the_patient_accepts_one(client, world, request_id):
    offered = _times(client, request_id)
    assert offered["in_time"] is True and offered["within_hours"] == 14 * 24
    first, second = offered["times"][:2]
    response = _propose(client, request_id, [second, first])
    assert response.status_code == 200 and response.json()["status"] == "proposed"
    mine = _mine(client)
    assert mine["status"] == "proposed" and len(mine["proposed_times"]) == 2
    booked = _schedule(client, request_id, second)
    assert booked.status_code == 200 and booked.json()["status"] == "scheduled"
    assert _mine(client)["scheduled_at"] is not None
    # The lab and the clinician both see it booked; the booked time is no longer free
    for headers in (LAB_TECH, CLINICIAN, PHYSICIAN):
        [row] = client.get("/lab/requests", headers=headers).json()
        assert row["status"] == "scheduled"
    assert second not in _times(client, request_id)["times"]


def test_a_finished_request_moves_to_the_past_list(client, world, request_id):
    """Booked or completed, a request never just disappears: it is listed, then listed as done."""
    first = _times(client, request_id)["times"][0]
    _propose(client, request_id, [first])
    _schedule(client, request_id, first)
    [booked] = client.get("/lab/requests", headers=LAB_TECH).json()
    assert booked["status"] == "scheduled" and booked["updated_at"] is not None
    cancelled = client.patch(
        f"/lab/requests/{request_id}", json={"status": "cancelled"}, headers=LAB_TECH
    )
    assert cancelled.status_code == 200
    assert client.get("/lab/requests", headers=LAB_TECH).json() == []
    [past] = client.get("/lab/requests?status=done", headers=LAB_TECH).json()
    assert past["status"] == "cancelled" and past["scheduled_at"] is not None
    assert past["updated_at"] >= booked["updated_at"]


def test_the_patient_can_choose_another_free_time(client, world, request_id):
    _propose(client, request_id, _times(client, request_id)["times"][:1])
    mine = _times(client, request_id, headers=PATIENT)
    own = mine["times"][5]
    assert _schedule(client, request_id, own).status_code == 200
    # ...and move it again later
    assert _schedule(client, request_id, mine["times"][6]).status_code == 200


def test_times_that_dont_fit_are_refused(client, world, request_id):
    now = datetime.now(UTC)
    too_late = next(t for t in _candidates(now) if t > now + timedelta(days=15))
    off_hours = (now + timedelta(days=2)).replace(hour=3, minute=0, second=0, microsecond=0)
    for at in (too_late.isoformat(), off_hours.isoformat()):
        assert _propose(client, request_id, [at]).status_code == 422
        assert _schedule(client, request_id, at).status_code == 409


def test_two_patients_never_get_the_same_lab_time(client, world, request_id):
    slot = world.execute(
        "INSERT INTO slots (provider_id, starts_at, ends_at) "
        "VALUES (1, '2030-01-08 09:00+00', '2030-01-08 09:30+00') RETURNING id"
    ).fetchone()[0]
    visit = world.execute(
        "INSERT INTO appointments (patient_id, slot_id) VALUES (2, %s) RETURNING id", (slot,)
    ).fetchone()[0]
    other = client.post(
        f"/appointments/{visit}/lab-requests",
        json={"exam_type": "blood", "urgency": "routine"},
        headers=CLINICIAN,
    ).json()["id"]
    at = _times(client, request_id)["times"][0]
    assert _schedule(client, request_id, at).status_code == 200
    taken = _schedule(client, other, at, headers=OTHER)
    assert taken.status_code == 409


def test_only_the_right_people_act(client, world, request_id):
    at = _times(client, request_id)["times"][0]
    assert client.get(f"/lab/requests/{request_id}/times", headers=PATIENT).status_code == 403
    assert _propose(client, request_id, [at]).status_code == 200
    assert (
        client.post(
            f"/lab/requests/{request_id}/propose", json={"times": [at]}, headers=CLINICIAN
        ).status_code
        == 403
    )
    assert _schedule(client, request_id, at, headers=OTHER).status_code == 404
    assert _schedule(client, request_id, at, headers=LAB_TECH).status_code == 403
