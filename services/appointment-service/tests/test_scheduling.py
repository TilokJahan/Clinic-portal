"""The urgency matrix and choosing when to be seen: timeframes, limits and patient rescheduling."""

import pytest

from app import metrics, urgency
from tests.conftest import as_user

PATIENT = as_user(1)
OTHER = as_user(2)
CLINICIAN = as_user(3, role="clinician", email="doc@example.com")

# Slot ids, in the order the fixture creates them
CURRENT, IN_2H, IN_30H, IN_4D, IN_10D, PAST, IN_20D, DR_TWO_IN_3H = range(1, 9)
APPOINTMENT = 1  # patient 1's visit, in CURRENT (5 days away)


@pytest.fixture
def world(db):
    """Patients 1 and 2 and clinician 3. Patient 1 has appointment 1 with Dr. One in 5 days."""
    db.execute(
        "INSERT INTO providers (name, specialty) VALUES "
        "('Dr. One', 'General Practice'), ('Dr. Two', 'Dermatology')"
    )
    db.execute(
        "INSERT INTO users (email, role) VALUES ('p1@example.com', 'patient'), "
        "('p2@example.com', 'patient'), ('doc@example.com', 'clinician')"
    )
    db.execute(
        """
        INSERT INTO slots (provider_id, starts_at, ends_at) VALUES
            (1, now() + interval '5 days', now() + interval '5 days 30 minutes'),
            (1, now() + interval '2 hours', now() + interval '2 hours 30 minutes'),
            (1, now() + interval '30 hours', now() + interval '30 hours 30 minutes'),
            (1, now() + interval '4 days', now() + interval '4 days 30 minutes'),
            (1, now() + interval '10 days', now() + interval '10 days 30 minutes'),
            (1, now() - interval '1 hour', now() - interval '30 minutes'),
            (1, now() + interval '20 days', now() + interval '20 days 30 minutes'),
            (2, now() + interval '3 hours', now() + interval '3 hours 30 minutes')
        """
    )
    db.execute("INSERT INTO appointments (patient_id, slot_id) VALUES (1, 1)")
    return db


def _triage(db, ai="routine", appointment=APPOINTMENT):
    db.execute(
        "INSERT INTO triage_results (appointment_id, ai_urgency, summary) VALUES (%s, %s, 's')",
        (appointment, ai),
    )


def _lab(db, lab_urgency="urgent", appointment=APPOINTMENT):
    db.execute(
        "INSERT INTO lab_reports (appointment_id, blob_name, content_type, size_bytes, status, "
        "lab_urgency, reason, processed_at) VALUES (%s, 'test/1.pdf', 'application/pdf', 10, "
        "'ready', %s, 'Critical: potassium 6.8 mmol/L', now())",
        (appointment, lab_urgency),
    )


def _options(client, within=None, appointment=APPOINTMENT, headers=PATIENT):
    params = {} if within is None else {"within_hours": within}
    return client.get(
        f"/appointments/{appointment}/schedule-options", params=params, headers=headers
    )


def _move(client, slot, appointment=APPOINTMENT, headers=PATIENT):
    return client.post(
        f"/appointments/{appointment}/reschedule", json={"slot_id": slot}, headers=headers
    )


def _ids(slots):
    return [s["id"] for s in slots]


# --- the matrix ---------------------------------------------------------------------------------


@pytest.mark.parametrize("headers", [PATIENT, CLINICIAN])
def test_everyone_signed_in_can_read_the_matrix(client, world, headers):
    body = client.get("/urgency-matrix", headers=headers).json()
    assert [(lv["urgency"], lv["seen_within_hours"]) for lv in body["levels"]] == [
        ("urgent", 24),
        ("soon", 72),
        ("routine", 336),
    ]
    assert [t["hours"] for t in body["timeframes"]] == [24, 72, 168, 336]
    assert all(lv["symptom_signals"] and lv["lab_signals"] for lv in body["levels"])


def test_the_matrix_needs_a_sign_in(client, world):
    assert client.get("/urgency-matrix").status_code == 401


def test_every_level_limit_is_one_of_the_timeframes():
    assert set(urgency.SEEN_WITHIN_HOURS.values()) <= urgency.TIMEFRAME_HOURS


# --- booking by timeframe -----------------------------------------------------------------------


def test_earliest_slots_are_free_upcoming_and_inside_the_timeframe(client, world):
    def earliest(hours, **params):
        response = client.get(
            "/slots/earliest", params={"within_hours": hours, **params}, headers=PATIENT
        )
        return _ids(response.json())

    assert earliest(24) == [IN_2H, DR_TWO_IN_3H]
    assert earliest(72) == [IN_2H, DR_TWO_IN_3H, IN_30H]
    assert earliest(336) == [IN_2H, DR_TWO_IN_3H, IN_30H, IN_4D, IN_10D]  # CURRENT is booked
    assert earliest(72, provider_id=2) == [DR_TWO_IN_3H]


def test_only_the_listed_timeframes_are_accepted(client, world):
    response = client.get("/slots/earliest", params={"within_hours": 5}, headers=PATIENT)
    assert response.status_code == 422
    assert "24, 72, 168, 336" in response.json()["detail"]


# --- schedule options for a booked visit --------------------------------------------------------


def test_without_an_intake_every_timeframe_is_allowed(client, world):
    body = _options(client).json()
    assert body["priority"] is None and body["care_team_limit"] is False
    assert body["max_within_hours"] == body["within_hours"] == 336
    assert _ids(body["slots"]) == [IN_2H, DR_TWO_IN_3H, IN_30H, IN_4D, IN_10D]
    assert body["current_fits"] is True  # 5 days away, inside 2 weeks


def test_the_chosen_timeframe_narrows_the_times(client, world):
    body = _options(client, within=72).json()
    assert _ids(body["slots"]) == [IN_2H, DR_TWO_IN_3H, IN_30H]
    assert body["current_fits"] is False


@pytest.mark.parametrize(("ai", "limit"), [("urgent", 24), ("soon", 72), ("routine", 336)])
def test_the_priority_sets_the_longest_timeframe(client, world, ai, limit):
    _triage(world, ai)
    body = _options(client).json()
    assert (body["priority"], body["max_within_hours"], body["within_hours"]) == (ai, limit, limit)
    assert body["care_team_limit"] is False


def test_asking_for_a_later_timeframe_than_allowed_is_refused(client, world):
    _triage(world, "urgent")
    response = _options(client, within=72)
    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Your care team needs to see you within 24 hours. Please choose an earlier time."
    )


def test_an_urgent_lab_limits_the_timeframe_without_showing_the_result(client, world):
    _triage(world, "routine")
    _lab(world, "urgent")
    body = _options(client).json()
    # The patient keeps seeing their own priority; only the limit says the care team needs them
    assert body["priority"] == "routine"
    assert body["max_within_hours"] == 24 and body["care_team_limit"] is True
    assert "potassium" not in str(body)


def test_a_clinician_decision_after_the_lab_is_final(client, world):
    _triage(world, "routine")
    _lab(world, "urgent")
    client.patch("/triage/1", json={"final_urgency": "soon"}, headers=CLINICIAN)
    assert _options(client).json()["max_within_hours"] == 72


def test_options_are_only_for_your_own_booked_visit(client, world):
    assert _options(client, headers=OTHER).status_code == 404
    assert _options(client, appointment=99).status_code == 404
    assert _options(client, headers=CLINICIAN).status_code == 403
    world.execute("UPDATE appointments SET status = 'cancelled' WHERE id = 1")
    assert _options(client).status_code == 409


# --- accepting a new time -----------------------------------------------------------------------


def test_accepting_a_time_moves_the_visit_with_the_intake_and_labs(client, world):
    _triage(world, "soon")
    _lab(world, "soon")
    response = _move(client, IN_30H)
    assert response.status_code == 200
    new = response.json()
    assert new["slot_id"] == IN_30H and new["intake_submitted"] is True
    assert _ids(client.get("/appointments", headers=PATIENT).json()) == [new["id"]]
    old = world.execute("SELECT status FROM appointments WHERE id = 1").fetchone()[0]
    assert old == "cancelled"
    for table in ("triage_results", "lab_reports"):
        moved = world.execute(f"SELECT appointment_id FROM {table}").fetchone()[0]
        assert moved == new["id"]
    queue = client.get("/queue", headers=CLINICIAN).json()
    assert [e["appointment_id"] for e in queue] == [new["id"]]


def test_a_time_later_than_the_priority_allows_is_refused(client, world):
    _triage(world, "urgent")
    response = _move(client, IN_30H)
    assert response.status_code == 422
    assert "within 24 hours" in response.json()["detail"]
    assert _move(client, IN_2H).status_code == 200


def test_moving_to_a_later_time_is_fine_within_the_limit(client, world):
    assert _move(client, IN_10D).status_code == 200


@pytest.mark.parametrize(
    ("slot", "code", "detail"),
    [
        (99, 404, "Slot not found"),
        (PAST, 409, "Slot has already started"),
        (CURRENT, 409, "Slot is already booked"),
        (IN_20D, 422, None),
    ],
)
def test_the_new_time_must_exist_be_upcoming_free_and_in_range(client, world, slot, code, detail):
    response = _move(client, slot)
    assert response.status_code == code
    if detail:
        assert response.json()["detail"] == detail
    status = world.execute("SELECT status FROM appointments WHERE id = 1").fetchone()[0]
    assert status == "booked"


def test_a_time_someone_else_booked_is_refused(client, world):
    world.execute("INSERT INTO appointments (patient_id, slot_id) VALUES (2, %s)", (IN_2H,))
    assert _move(client, IN_2H).status_code == 409


def test_only_the_patient_can_move_their_visit(client, world):
    assert _move(client, IN_2H, headers=OTHER).status_code == 404
    assert _move(client, IN_2H, headers=CLINICIAN).status_code == 403


def test_moving_yourself_closes_an_open_offer(client, world):
    _lab(world, "urgent")
    offer = client.post(
        "/appointments/1/reschedule-offers", json={"slot_id": IN_2H}, headers=CLINICIAN
    ).json()
    assert _move(client, DR_TWO_IN_3H).status_code == 200
    status = world.execute(
        "SELECT status FROM reschedule_offers WHERE id = %s", (offer["id"],)
    ).fetchone()[0]
    assert status == "expired"
    assert (
        client.post(f"/reschedule-offers/{offer['id']}/accept", headers=PATIENT).status_code == 409
    )


def test_moves_are_counted(client, world):
    before = metrics.PATIENT_RESCHEDULES._value.get()
    _move(client, IN_2H)
    assert metrics.PATIENT_RESCHEDULES._value.get() == before + 1
