"""Earlier-visit offers: a clinician offers an urgent patient an earlier slot; they decide."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from app import metrics
from tests.conftest import DB_DIR, as_user

PATIENT = as_user(1)
OTHER = as_user(2)
CLINICIAN = as_user(3, role="clinician", email="doc@example.com")
LAB_TECH = as_user(4, role="lab_tech", email="tech@example.com")

# Slot ids, in the order the fixture creates them
S1, S2, E1, E2, E3, PAST, OTHER_PROVIDER, LATER = range(1, 9)
OLD = 1  # patient 1's appointment, in S1 (3 days away)


@pytest.fixture
def world(db):
    """Patients 1 and 2, clinician 3, lab tech 4. Patient 1 has appointment 1 in 3 days and
    patient 2 appointment 2 in 4 days, both with Dr. One. Free slots to move to: E1 (in 2 hours),
    E2 (5 hours) and E3 (30 hours); a slot in the past, one with Dr. Two and one 10 days away."""
    db.execute(
        "INSERT INTO providers (name, specialty) VALUES "
        "('Dr. One', 'General Practice'), ('Dr. Two', 'Dermatology')"
    )
    db.execute(
        "INSERT INTO users (email, role) VALUES ('p1@example.com', 'patient'), "
        "('p2@example.com', 'patient'), ('doc@example.com', 'clinician'), "
        "('tech@example.com', 'lab_tech')"
    )
    db.execute(
        """
        INSERT INTO slots (provider_id, starts_at, ends_at) VALUES
            (1, now() + interval '3 days', now() + interval '3 days 30 minutes'),
            (1, now() + interval '4 days', now() + interval '4 days 30 minutes'),
            (1, now() + interval '2 hours', now() + interval '2 hours 30 minutes'),
            (1, now() + interval '5 hours', now() + interval '5 hours 30 minutes'),
            (1, now() + interval '30 hours', now() + interval '30 hours 30 minutes'),
            (1, now() - interval '1 hour', now() - interval '30 minutes'),
            (2, now() + interval '3 hours', now() + interval '3 hours 30 minutes'),
            (1, now() + interval '10 days', now() + interval '10 days 30 minutes')
        """
    )
    db.execute("INSERT INTO appointments (patient_id, slot_id) VALUES (1, 1), (2, 2)")
    return db


def _urgent_lab(db, appointment=OLD, urgency="urgent"):
    db.execute(
        "INSERT INTO lab_reports (appointment_id, blob_name, content_type, size_bytes, status, "
        "lab_urgency, reason, processed_at) VALUES (%s, %s, 'application/pdf', 10, 'ready', %s, "
        "'Critical: potassium 6.8 mmol/L', now())",
        (appointment, f"test/{appointment}.pdf", urgency),
    )


def _offer(client, appointment=OLD, slot=E1, headers=CLINICIAN, **body):
    return client.post(
        f"/appointments/{appointment}/reschedule-offers",
        json={"slot_id": slot, **body},
        headers=headers,
    )


def _accept(client, offer_id, headers=PATIENT):
    return client.post(f"/reschedule-offers/{offer_id}/accept", headers=headers)


def _decline(client, offer_id, headers=PATIENT):
    return client.post(f"/reschedule-offers/{offer_id}/decline", headers=headers)


def _entry(client, appointment=OLD):
    queue = client.get("/queue", headers=CLINICIAN).json()
    return next(e for e in queue if e["appointment_id"] == appointment)


def _offer_status(db, offer_id):
    row = db.execute("SELECT status FROM reschedule_offers WHERE id = %s", (offer_id,)).fetchone()
    return row[0]


def _refused(response, code, detail):
    """True if the API refused with this status and message."""
    return (response.status_code, response.json()["detail"]) == (code, detail)


def _status(db, appointment):
    return db.execute("SELECT status FROM appointments WHERE id = %s", (appointment,)).fetchone()[0]


# --- the queue flag ---------------------------------------------------------------------------


def test_an_urgent_lab_three_days_away_needs_an_earlier_visit(client, world):
    _urgent_lab(world)
    entry = _entry(client)
    assert entry["urgency"] == "urgent"
    assert entry["needs_earlier_visit"] is True and entry["offer_pending"] is False


@pytest.mark.parametrize("urgency", ["routine", "soon"])
def test_a_less_urgent_lab_does_not(client, world, urgency):
    _urgent_lab(world, urgency=urgency)
    assert _entry(client)["needs_earlier_visit"] is False


def test_a_patient_with_no_intake_or_lab_does_not(client, world):
    assert _entry(client)["needs_earlier_visit"] is False


def test_an_urgent_patient_seen_within_24_hours_does_not(client, world):
    world.execute("UPDATE appointments SET slot_id = %s WHERE id = %s", (E1, OLD))
    _urgent_lab(world)
    assert _entry(client)["needs_earlier_visit"] is False


def test_a_checked_in_patient_does_not(client, world):
    _urgent_lab(world)
    world.execute("UPDATE appointments SET status = 'checked_in' WHERE id = 1")
    assert _entry(client)["needs_earlier_visit"] is False


def test_the_flag_goes_while_an_offer_is_open_and_returns_after_a_decline(client, world):
    _urgent_lab(world)
    offer_id = _offer(client).json()["id"]
    entry = _entry(client)
    assert entry["needs_earlier_visit"] is False and entry["offer_pending"] is True
    assert _decline(client, offer_id).status_code == 200
    entry = _entry(client)
    assert entry["needs_earlier_visit"] is True and entry["offer_pending"] is False


def test_an_offer_whose_slot_was_taken_no_longer_counts_as_open(client, world):
    _urgent_lab(world)
    _offer(client)
    assert client.post("/appointments", json={"slot_id": E1}, headers=OTHER).status_code == 201
    entry = _entry(client)
    assert entry["needs_earlier_visit"] is True and entry["offer_pending"] is False


# --- earlier slots ----------------------------------------------------------------------------


def test_earlier_slots_are_free_upcoming_and_with_the_same_provider(client, world):
    response = client.get(f"/appointments/{OLD}/earlier-slots", headers=CLINICIAN)
    assert response.status_code == 200
    slots = response.json()
    # Not the past slot, Dr. Two's, the later one, or the booked ones
    assert [s["id"] for s in slots] == [E1, E2, E3]
    assert {s["provider_name"] for s in slots} == {"Dr. One"}
    assert slots[0]["specialty"] == "General Practice"


def test_booked_slots_are_left_out_but_cancelled_ones_are_not(client, world):
    world.execute("INSERT INTO appointments (patient_id, slot_id) VALUES (2, %s)", (E2,))
    world.execute(
        "INSERT INTO appointments (patient_id, slot_id, status) VALUES (2, %s, 'cancelled')", (E3,)
    )
    slots = client.get(f"/appointments/{OLD}/earlier-slots", headers=CLINICIAN).json()
    assert [s["id"] for s in slots] == [E1, E3]


def test_earlier_slots_are_limited_to_ten_earliest_first(client, world):
    world.execute(
        "INSERT INTO slots (provider_id, starts_at, ends_at) "
        "SELECT 1, now() + interval '1 day' + n * interval '1 minute', "
        "now() + interval '1 day 30 minutes' + n * interval '1 minute' "
        "FROM generate_series(1, 12) n"
    )
    slots = client.get(f"/appointments/{OLD}/earlier-slots", headers=CLINICIAN).json()
    assert len(slots) == 10
    assert [s["starts_at"] for s in slots] == sorted(s["starts_at"] for s in slots)


def test_earlier_slots_checks_the_appointment_and_the_role(client, world):
    url = f"/appointments/{OLD}/earlier-slots"
    for headers in (PATIENT, LAB_TECH):
        assert client.get(url, headers=headers).status_code == 403
    assert client.get(url).status_code == 401
    assert client.get("/appointments/999/earlier-slots", headers=CLINICIAN).status_code == 404
    world.execute("UPDATE appointments SET status = 'cancelled' WHERE id = 1")
    assert client.get(url, headers=CLINICIAN).status_code == 409


# --- making an offer --------------------------------------------------------------------------


def test_a_clinician_offers_an_earlier_slot(client, world):
    response = _offer(client, reason="Potassium 6.8, see sooner")
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending" and body["reason"] == "Potassium 6.8, see sooner"
    assert body["appointment_id"] == OLD and body["proposed_slot_id"] == E1
    assert body["provider_name"] == "Dr. One"
    assert world.execute("SELECT offered_by FROM reschedule_offers").fetchone()[0] == 3
    # Nothing moves until the patient accepts
    assert _status(world, OLD) == "booked"
    assert world.execute("SELECT count(*) FROM appointments").fetchone()[0] == 2


@pytest.mark.parametrize(
    ("slot", "code", "detail"),
    [
        (LATER, 422, "The slot must be earlier than the current visit"),
        (S1, 422, "The slot must be earlier than the current visit"),
        (PAST, 409, "Slot has already started"),
        (999, 404, "Slot not found"),
    ],
)
def test_the_slot_must_exist_be_upcoming_and_earlier(client, world, slot, code, detail):
    response = _offer(client, slot=slot)
    assert (response.status_code, response.json()["detail"]) == (code, detail)


def test_a_booked_slot_cannot_be_offered(client, world):
    world.execute("INSERT INTO appointments (patient_id, slot_id) VALUES (2, %s)", (E1,))
    response = _offer(client)
    assert response.status_code == 409 and response.json()["detail"] == "Slot is already booked"


def test_only_one_offer_can_be_open_at_a_time(client, world):
    assert _offer(client).status_code == 201
    response = _offer(client, slot=E2)
    assert (
        response.status_code == 409 and response.json()["detail"] == "An offer is already pending"
    )


def test_a_lapsed_offer_does_not_block_a_new_one(client, world):
    first = _offer(client).json()["id"]
    client.post("/appointments", json={"slot_id": E1}, headers=OTHER)  # someone books E1
    assert _offer(client, slot=E2).status_code == 201
    assert _offer_status(world, first) == "expired"


def test_offers_need_a_booked_appointment_and_a_clinician(client, world):
    assert _offer(client, appointment=999).status_code == 404
    for headers in (PATIENT, LAB_TECH):
        assert _offer(client, headers=headers).status_code == 403
    assert (
        client.post(f"/appointments/{OLD}/reschedule-offers", json={"slot_id": E1}).status_code
        == 401
    )
    world.execute("UPDATE appointments SET status = 'cancelled' WHERE id = 1")
    assert _offer(client).status_code == 409


# --- what the patient sees --------------------------------------------------------------------


def test_the_patient_sees_the_pending_offer_and_no_clinical_detail(client, world):
    offer_id = _offer(client, reason="Potassium 6.8").json()["id"]
    [mine] = client.get("/appointments", headers=PATIENT).json()
    offer = mine["pending_offer"]
    assert set(offer) == {"id", "slot_id", "starts_at", "provider_name"}
    assert (
        offer["id"] == offer_id and offer["slot_id"] == E1 and offer["provider_name"] == "Dr. One"
    )
    assert "Potassium" not in client.get("/appointments", headers=PATIENT).text
    # The other patient sees nothing of it
    [theirs] = client.get("/appointments", headers=OTHER).json()
    assert theirs["pending_offer"] is None


def test_an_offer_for_a_slot_that_was_taken_is_not_shown(client, world):
    _offer(client)
    client.post("/appointments", json={"slot_id": E1}, headers=OTHER)
    [mine] = client.get("/appointments", headers=PATIENT).json()
    assert mine["pending_offer"] is None


# --- accepting --------------------------------------------------------------------------------


def test_accepting_moves_the_patient_with_the_intake_and_labs(client, world):
    world.execute(
        "INSERT INTO triage_results (appointment_id, ai_urgency, summary) VALUES (1, 'soon', 's')"
    )
    _urgent_lab(world)
    offer_id = _offer(client).json()["id"]

    response = _accept(client, offer_id)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 3 and body["slot_id"] == E1 and body["status"] == "booked"
    assert body["intake_submitted"] is True and body["pending_offer"] is None
    assert body["provider_name"] == "Dr. One"

    assert _status(world, OLD) == "cancelled" and _status(world, 3) == "booked"
    assert world.execute("SELECT appointment_id FROM triage_results").fetchone()[0] == 3
    assert world.execute("SELECT appointment_id FROM lab_reports").fetchone()[0] == 3
    assert _offer_status(world, offer_id) == "accepted"
    assert world.execute("SELECT responded_at FROM reschedule_offers").fetchone()[0] is not None
    assert [a["id"] for a in client.get("/appointments", headers=PATIENT).json()] == [3]


def test_after_accepting_the_queue_shows_the_patient_once_at_the_new_time(client, world):
    world.execute(
        "INSERT INTO triage_results (appointment_id, ai_urgency, summary) VALUES (1, 'soon', 's')"
    )
    _urgent_lab(world)
    old_start = _entry(client)["starts_at"]
    _accept(client, _offer(client).json()["id"])
    queue = client.get("/queue", headers=CLINICIAN).json()
    mine = [e for e in queue if e["patient_label"] == "Patient 0001"]
    assert len(mine) == 1
    assert mine[0]["appointment_id"] == 3 and mine[0]["starts_at"] < old_start
    assert mine[0]["triage"] is not None and mine[0]["lab"]["urgency"] == "urgent"
    assert mine[0]["urgency"] == "urgent" and mine[0]["needs_earlier_visit"] is False


def test_an_offer_can_only_be_used_once(client, world):
    offer_id = _offer(client).json()["id"]
    assert _accept(client, offer_id).status_code == 200
    again = _accept(client, offer_id)
    assert (
        again.status_code == 409 and again.json()["detail"] == "This offer is no longer available"
    )
    assert _decline(client, offer_id).status_code == 409
    assert world.execute("SELECT count(*) FROM appointments").fetchone()[0] == 3


def test_a_declined_offer_cannot_be_accepted(client, world):
    offer_id = _offer(client).json()["id"]
    response = _decline(client, offer_id)
    assert response.status_code == 200 and response.json() == {"id": offer_id, "status": "declined"}
    assert _accept(client, offer_id).status_code == 409
    assert _decline(client, offer_id).status_code == 409
    assert _status(world, OLD) == "booked"  # the original booking is untouched
    assert world.execute("SELECT count(*) FROM appointments").fetchone()[0] == 2


def test_a_declined_offer_can_be_followed_by_a_new_one(client, world):
    _decline(client, _offer(client).json()["id"])
    assert _offer(client, slot=E2).status_code == 201


def test_accepting_after_the_slot_was_taken_is_a_409_and_the_offer_expires(client, world):
    offer_id = _offer(client).json()["id"]
    client.post("/appointments", json={"slot_id": E1}, headers=OTHER)
    assert _refused(_accept(client, offer_id), 409, "That time was just taken")
    assert _offer_status(world, offer_id) == "expired"
    assert _status(world, OLD) == "booked"  # the patient keeps the original visit
    assert _accept(client, offer_id).status_code == 409  # and the offer stays dead


def test_accepting_after_the_slot_started_is_a_409(client, world):
    offer_id = _offer(client).json()["id"]
    world.execute(
        "UPDATE slots SET starts_at = now() - interval '1 minute', "
        "ends_at = now() + interval '29 minutes' WHERE id = %s",
        (E1,),
    )
    response = _accept(client, offer_id)
    assert (
        response.status_code == 409 and response.json()["detail"] == "That time has already started"
    )
    assert _offer_status(world, offer_id) == "expired"


def test_accepting_after_the_original_visit_was_cancelled_is_a_409(client, world):
    offer_id = _offer(client).json()["id"]
    world.execute("UPDATE appointments SET status = 'cancelled' WHERE id = 1")
    response = _accept(client, offer_id)
    assert (
        response.status_code == 409 and response.json()["detail"] == "Your appointment has changed"
    )
    assert world.execute("SELECT count(*) FROM appointments").fetchone()[0] == 2  # nothing booked


def test_two_patients_racing_for_the_same_slot_one_wins(client, world):
    first = _offer(client, appointment=1).json()["id"]
    second = _offer(client, appointment=2).json()["id"]  # patient 2's visit is on day 4
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda args: _accept(client, *args), [(first, PATIENT), (second, OTHER)])
        )
    assert sorted(r.status_code for r in results) == [200, 409]
    active = world.execute(
        "SELECT count(*) FROM appointments WHERE slot_id = %s AND status <> 'cancelled'", (E1,)
    ).fetchone()[0]
    assert active == 1
    # The loser keeps their original booking
    winner, loser = (1, 2) if results[0].status_code == 200 else (2, 1)
    assert _status(world, winner) == "cancelled" and _status(world, loser) == "booked"
    assert _offer_status(world, second if loser == 2 else first) == "expired"


# --- who may act ------------------------------------------------------------------------------


def test_patients_cannot_act_on_someone_elses_offer(client, world):
    offer_id = _offer(client).json()["id"]  # patient 1's offer
    assert _accept(client, offer_id, headers=OTHER).status_code == 404
    assert _decline(client, offer_id, headers=OTHER).status_code == 404
    assert _offer_status(world, offer_id) == "pending"  # untouched


def test_only_patients_answer_offers(client, world):
    offer_id = _offer(client).json()["id"]
    for headers in (CLINICIAN, LAB_TECH):
        assert _accept(client, offer_id, headers=headers).status_code == 403
        assert _decline(client, offer_id, headers=headers).status_code == 403
    assert client.post(f"/reschedule-offers/{offer_id}/accept").status_code == 401
    assert client.post(f"/reschedule-offers/{offer_id}/decline").status_code == 401


def test_unknown_offers_are_404(client, world):
    assert _accept(client, 999).status_code == 404
    assert _decline(client, 999).status_code == 404


# --- metrics, live queue and the migration ----------------------------------------------------


def _count(outcome):
    return metrics.RESCHEDULE_OFFERS.labels(outcome)._value.get()


def test_metrics_count_offers_by_outcome(client, world):
    before = {o: _count(o) for o in ("offered", "accepted", "declined", "expired")}
    _decline(client, _offer(client).json()["id"])
    _accept(client, _offer(client, slot=E2).json()["id"])
    assert _count("offered") == before["offered"] + 2
    assert _count("declined") == before["declined"] + 1
    assert _count("accepted") == before["accepted"] + 1
    assert _count("expired") == before["expired"]


def test_an_offer_notifies_the_live_queue(client, world):
    world.execute("LISTEN queue_changed")
    _offer(client)
    payloads = {n.payload for n in world.notifies(timeout=2, stop_after=1)}
    assert "reschedule_offers" in payloads


def test_the_migration_can_run_twice(world):
    migration = (DB_DIR / "schemav5_reschedule.sql").read_text()
    world.execute(migration)
    world.execute(migration)
    # Only the trigger on this schema's table (a dev database also has one in public)
    triggers = world.execute(
        "SELECT count(*) FROM pg_trigger "
        "WHERE tgrelid = 'reschedule_offers'::regclass "
        "AND tgname = 'reschedule_offers_queue_changed'"
    ).fetchone()[0]
    assert triggers == 1
