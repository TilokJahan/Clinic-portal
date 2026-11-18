"""Physicians, admins, kinds of tests, suggested tests and lab requests."""

from datetime import UTC, datetime, timedelta

import pytest

from app.lab_needs import suggested_tests
from tests.conftest import as_user
from tests.test_labs import PDF, lab_setup  # noqa: F401  (fixture)

PATIENT = as_user(1, email="p1@example.com")
OTHER = as_user(2, email="p2@example.com")
CLINICIAN = as_user(3, role="clinician", email="doc@example.com")
LAB_TECH = as_user(4, role="lab_tech", email="tech@example.com")
PHYSICIAN = as_user(5, role="physician", email="phys1@example.com")
OTHER_PHYSICIAN = as_user(6, role="physician", email="phys2@example.com")
ADMIN = as_user(7, role="admin", email="admin@example.com")


@pytest.fixture
def world(lab_setup, db):  # noqa: F811
    """lab_setup (patients 1-2, clinician 3, lab tech 4, appointment 1 with Dr. One) plus
    physician 5 on Dr. One's schedule, physician 6 on Dr. Two's, and admin 7."""
    db.execute("INSERT INTO providers (name, specialty) VALUES ('Dr. Two', 'Cardiology')")
    db.execute(
        "INSERT INTO users (email, role, provider_id) VALUES "
        "('phys1@example.com', 'physician', 1), ('phys2@example.com', 'physician', 2), "
        "('admin@example.com', 'admin', NULL)"
    )
    # Patient 1's visit has a triage that suggests a blood test and an ultrasound
    db.execute(
        "INSERT INTO triage_results (appointment_id, patient_id, ai_urgency, summary, "
        "suggested_tests) VALUES (1, 1, 'soon', 'Belly pain and tiredness.', "
        "'{blood,ultrasound}')"
    )
    return db


def _upload(client, exam_type="blood", taken_on=None, headers=PATIENT, **extra):
    data = {"exam_type": exam_type, **({"taken_on": taken_on} if taken_on else {}), **extra}
    url = "/appointments/1/lab-reports" if headers == PATIENT else "/lab/appointments/1/reports"
    return client.post(url, files={"file": PDF}, data=data, headers=headers)


def _needs(client):
    [entry] = client.get("/queue", headers=CLINICIAN).json()
    return {n["exam_type"]: n["status"] for n in entry["lab_needs"]}


def _request(client, exam_type="ultrasound", urgency="soon", headers=CLINICIAN, note="Lower RLQ"):
    return client.post(
        "/appointments/1/lab-requests",
        json={"exam_type": exam_type, "urgency": urgency, "note": note},
        headers=headers,
    )


# --- suggested tests ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("symptoms", "expected"),
    [
        ("Sharp abdominal pain on the lower right since yesterday", ["ultrasound"]),
        ("I feel tired and dizzy all the time", ["blood"]),
        ("Chest pain and my heart racing", ["ecg"]),
        ("Burning when I pee", ["urine"]),
        ("I fell down the stairs and think my wrist is broken", ["xray"]),
        ("A mild sore throat", []),
    ],
)
def test_symptoms_suggest_tests(symptoms, expected):
    assert suggested_tests(symptoms) == expected


# --- kinds of tests ----------------------------------------------------------------------------


def test_an_imaging_report_goes_to_a_clinician_without_ocr(client, world):
    response = _upload(client, exam_type="ultrasound", taken_on=str(datetime.now(UTC).date()))
    assert response.status_code == 202
    [report] = client.get("/appointments/1/lab-reports", headers=CLINICIAN).json()
    assert report["exam_type"] == "ultrasound" and report["status"] == "needs_review"
    assert "clinician reads it" in report["reason"]


def test_bad_kinds_and_dates_are_refused(client, world):
    assert _upload(client, exam_type="xyz").status_code == 422
    tomorrow = str(datetime.now(UTC).date() + timedelta(days=1))
    assert _upload(client, taken_on=tomorrow).status_code == 422


def test_the_clinician_sees_what_is_missing_outdated_recent_or_requested(client, world):
    assert _needs(client) == {"blood": "missing", "ultrasound": "missing"}
    old = str(datetime.now(UTC).date() - timedelta(days=60))
    _upload(client, exam_type="blood", taken_on=old)
    assert _needs(client)["blood"] == "outdated"
    _upload(client, exam_type="blood", taken_on=str(datetime.now(UTC).date() - timedelta(days=5)))
    assert _needs(client)["blood"] == "recent"
    assert _request(client).status_code == 201
    assert _needs(client)["ultrasound"] == "requested"


# --- lab requests ------------------------------------------------------------------------------


def test_lab_requests_reach_the_lab_most_urgent_first(client, world):
    assert _request(client, "blood", "routine").status_code == 201
    assert _request(client, "ultrasound", "urgent", headers=PHYSICIAN).status_code == 201
    duplicate = _request(client, "blood", "soon")
    assert duplicate.status_code == 409 and "already requested" in duplicate.json()["detail"]
    assert _request(client, headers=PATIENT).status_code == 403
    assert _request(client, headers=LAB_TECH).status_code == 403
    listed = client.get("/lab/requests", headers=LAB_TECH).json()
    assert [(r["exam_type"], r["urgency"]) for r in listed] == [
        ("ultrasound", "urgent"),
        ("blood", "routine"),
    ]
    assert listed[0]["patient_label"] == "Patient 0001" and listed[0]["note"] == "Lower RLQ"
    assert "summary" not in listed[0]
    # Clinical staff can follow the lab list; patients can't see it
    assert client.get("/lab/requests", headers=CLINICIAN).status_code == 200
    assert client.get("/lab/requests", headers=PATIENT).status_code == 403


def test_uploading_with_the_request_completes_it(client, world):
    request_id = _request(client).json()["id"]
    response = _upload(client, exam_type="ultrasound", headers=LAB_TECH, request_id=request_id)
    assert response.status_code == 202
    assert client.get("/lab/requests", headers=LAB_TECH).json() == []
    done = client.get("/lab/requests", params={"status": "done"}, headers=LAB_TECH).json()
    assert done[0]["status"] == "completed"
    assert _needs(client)["ultrasound"] == "recent"
    again = _upload(client, exam_type="ultrasound", headers=LAB_TECH, request_id=request_id)
    assert again.status_code == 409


def test_the_lab_can_schedule_or_cancel_a_request(client, world):
    request_id = _request(client).json()["id"]
    url = f"/lab/requests/{request_id}"
    assert client.patch(url, json={"status": "scheduled"}, headers=LAB_TECH).json()["status"] == (
        "scheduled"
    )
    assert client.patch(url, json={"status": "cancelled"}, headers=LAB_TECH).status_code == 200
    assert client.patch(url, json={"status": "scheduled"}, headers=LAB_TECH).status_code == 404


def test_the_patient_sees_requests_without_the_staff_note(client, world):
    _request(client)
    [mine] = client.get("/appointments", headers=PATIENT).json()
    assert mine["lab_requests"][0]["exam_type"] == "ultrasound"
    assert mine["lab_requests"][0]["note"] is None
    assert mine["reason_summary"] == "Belly pain and tiredness." and mine["priority"] == "soon"


# --- physicians --------------------------------------------------------------------------------


def test_a_physician_sees_only_their_own_schedule(client, world):
    mine = client.get("/physician/schedule", headers=PHYSICIAN)
    assert mine.status_code == 200 and [e["appointment_id"] for e in mine.json()] == [1]
    assert client.get("/physician/schedule", headers=OTHER_PHYSICIAN).json() == []
    assert client.get("/physician/schedule", headers=CLINICIAN).status_code == 403
    assert len(client.get("/physician/schedule", headers=ADMIN).json()) == 1


def test_completing_a_visit_needs_approval_and_leaves_a_summary(client, world):
    body = {"summary": "Ultrasound normal. Rest and fluids; come back if it gets worse."}
    url = "/appointments/1/complete"
    world.execute("UPDATE appointments SET approved_at = NULL WHERE id = 1")
    assert client.post(url, json=body, headers=PHYSICIAN).status_code == 409
    world.execute("UPDATE appointments SET approved_at = now() WHERE id = 1")
    assert client.post(url, json=body, headers=OTHER_PHYSICIAN).status_code == 404
    done = client.post(url, json=body, headers=PHYSICIAN)
    assert done.status_code == 200 and done.json()["status"] == "completed"
    [mine] = client.get("/appointments", headers=PATIENT).json()
    assert mine["visit_summary"] == body["summary"] and mine["completed_at"] is not None
    assert client.post(url, json=body, headers=PHYSICIAN).status_code == 409


def test_physicians_read_and_approve_lab_reports(client, world):
    _upload(client, exam_type="ultrasound")
    [report] = client.get("/appointments/1/lab-reports", headers=PHYSICIAN).json()
    response = client.patch(
        f"/lab-reports/{report['id']}",
        json={"patient_explanation": "Your ultrasound looked normal."},
        headers=PHYSICIAN,
    )
    assert response.status_code == 200 and response.json()["explanation_approved"] is True


# --- admin -------------------------------------------------------------------------------------


def test_an_admin_manages_roles(client, world):
    users = client.get("/admin/users", headers=ADMIN).json()
    assert users[0]["role"] == "admin" and {u["role"] for u in users} >= {"physician", "patient"}
    assert client.get("/admin/users", headers=CLINICIAN).status_code == 403
    url = "/admin/users/2"
    assert client.patch(url, json={"role": "physician"}, headers=ADMIN).status_code == 422
    changed = client.patch(url, json={"role": "physician", "provider_id": 2}, headers=ADMIN)
    assert changed.status_code == 200
    assert changed.json()["provider_name"] == "Dr. Two"
    back = client.patch(url, json={"role": "patient", "provider_id": 2}, headers=ADMIN).json()
    assert back["provider_id"] is None
    assert client.patch("/admin/users/7", json={"role": "patient"}, headers=ADMIN).status_code == (
        409
    )
    assert len(client.get("/providers", headers=PATIENT).json()) == 2
