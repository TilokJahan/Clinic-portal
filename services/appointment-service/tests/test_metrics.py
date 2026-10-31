import re

from tests.conftest import as_user


def _value(text: str, sample: str) -> float:
    match = re.search(rf"^{re.escape(sample)} (\S+)$", text, re.M)
    return float(match.group(1)) if match else 0.0


def test_metrics_count_bookings_conflicts_and_use_route_templates(client, db):
    db.execute("INSERT INTO users (email, role) VALUES ('p1@example.com', 'patient')")
    db.execute("INSERT INTO providers (name, specialty) VALUES ('Dr. One', 'General Practice')")
    db.execute(
        "INSERT INTO slots (provider_id, starts_at, ends_at) "
        "VALUES (1, '2030-01-07 09:00+00', '2030-01-07 09:30+00')"
    )
    before = client.get("/metrics").text
    headers = as_user(1)
    client.post("/appointments", json={"slot_id": 1}, headers=headers)
    client.post("/appointments", json={"slot_id": 1}, headers=headers)  # 409
    client.patch("/triage/12345", json={"final_urgency": "soon"}, headers=headers)  # 403
    after = client.get("/metrics").text

    assert (
        _value(after, "appointments_booked_total") - _value(before, "appointments_booked_total")
        == 1
    )
    conflict = 'appointment_booking_conflicts_total{reason="already_booked"}'
    assert _value(after, conflict) - _value(before, conflict) == 1
    # Route templates, never raw ids, so labels can't hold data and don't explode
    assert 'route="/triage/{triage_id}"' in after
    assert "12345" not in after
