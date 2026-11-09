from contextlib import contextmanager

import pytest
from psycopg.rows import dict_row

from app import db as app_db
from app import labs
from app.storage import LocalStore, get_store
from app.triage import get_triage_client
from tests.conftest import DB_DIR, _connect, as_user

PATIENT = as_user(1, email="p1@example.com")
OTHER = as_user(2, email="p2@example.com")
CLINICIAN = as_user(3, role="clinician", email="doc@example.com")
LAB_TECH = as_user(4, role="lab_tech", email="tech@example.com")
PDF = ("report.pdf", b"%PDF-1.4 synthetic", "application/pdf")


def _interpretation(urgency="urgent", reason="Critical: potassium 6.8 mmol/L", status="ready"):
    return {
        "status": status,
        "urgency": urgency,
        "rule_urgency": urgency,
        "reason": reason,
        "clinician_summary": "Potassium critically high.",
        "patient_explanation": "One result was higher than usual. Your care team will call you.",
        "extraction_confidence": 0.97,
        "tokens_used": 321,
        "fallback": False,
        "results": [
            {
                "test_name": "Potassium",
                "display_name": "Potassium",
                "canonical": "potassium",
                "value": 6.8,
                "unit": "mmol/L",
                "ref_low": 3.5,
                "ref_high": 5.1,
                "flag": "critical_high",
                "confidence": 0.97,
                "needs_verification": False,
                "verification_reason": None,
            },
            {
                "test_name": "Sodium",
                "display_name": "Sodium",
                "canonical": "sodium",
                "value": 139,
                "unit": "mmol/L",
                "ref_low": 135,
                "ref_high": 145,
                "flag": "normal",
                "confidence": 0.99,
                "needs_verification": False,
                "verification_reason": None,
            },
        ],
    }


class FakeTriage:
    def __init__(self):
        self.result = _interpretation()
        self.error: Exception | None = None
        self.calls: list[tuple[bytes, str]] = []

    def interpret_lab(self, content, content_type):
        self.calls.append((content, content_type))
        if self.error:
            raise self.error
        return self.result

    def assess(self, symptoms):
        from app.models import TriageAssessment

        return TriageAssessment(urgency="routine", suggested_specialty="GP", summary="s"), 5


@pytest.fixture
def lab_setup(client, db, database_url, tmp_path, monkeypatch):
    """Patients 1 and 2, clinician 3, lab tech 4; patient 1 has appointment 1 (booked)."""
    from app.main import app

    db.execute(
        "INSERT INTO users (email, role) VALUES ('p1@example.com', 'patient'), "
        "('p2@example.com', 'patient'), ('doc@example.com', 'clinician'), "
        "('tech@example.com', 'lab_tech')"
    )
    db.execute("INSERT INTO providers (name, specialty) VALUES ('Dr. One', 'General Practice')")
    db.execute(
        "INSERT INTO slots (provider_id, starts_at, ends_at) "
        "VALUES (1, '2030-01-07 09:00+00', '2030-01-07 09:30+00')"
    )
    db.execute("INSERT INTO appointments (patient_id, slot_id) VALUES (1, 1)")

    store = LocalStore(str(tmp_path))
    triage = FakeTriage()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_triage_client] = lambda: triage

    @contextmanager
    def connection():  # the background task uses a pooled connection; point it at the test schema
        with _connect(database_url) as conn:
            conn.row_factory = dict_row
            yield conn

    monkeypatch.setattr(app_db, "connection", connection)
    return store, triage


def _upload(client, headers=PATIENT, file=PDF, appointment=1):
    return client.post(
        f"/appointments/{appointment}/lab-reports", files={"file": file}, headers=headers
    )


def _reports(client, headers):
    return client.get("/appointments/1/lab-reports", headers=headers).json()


# --- upload and processing --------------------------------------------------------------------


def test_upload_is_stored_and_processed_in_the_background(client, db, lab_setup):
    store, triage = lab_setup
    response = _upload(client)
    assert response.status_code == 202
    assert response.json()["status"] == "processing"  # what the patient sees right away
    # TestClient runs background tasks before returning, so processing is done now
    assert triage.calls == [(PDF[1], "application/pdf")]
    blob = db.execute("SELECT blob_name FROM lab_reports").fetchone()[0]
    assert store.read(blob) == PDF[1]
    assert "report" not in blob  # the original file name (often the patient's name) isn't kept
    [report] = _reports(client, CLINICIAN)
    assert report["status"] == "ready"
    assert report["reason"] == "Critical: potassium 6.8 mmol/L"
    assert [r["flag"] for r in report["results"]] == ["critical_high", "normal"]


def test_patients_see_nothing_until_a_clinician_approves(client, lab_setup):
    _upload(client)
    [before] = _reports(client, PATIENT)
    assert before["status"] == "ready" and before["explanation_approved"] is False
    assert before["results"] == [] and before["patient_explanation"] is None
    assert before["reason"] is None and before["lab_urgency"] is None

    report_id = before["id"]
    edited = "Your potassium was high. A nurse will call you today."
    response = client.patch(
        f"/lab-reports/{report_id}", json={"patient_explanation": edited}, headers=CLINICIAN
    )
    assert response.status_code == 200 and response.json()["explanation_approved"] is True

    [after] = _reports(client, PATIENT)
    assert after["patient_explanation"] == edited
    assert len(after["results"]) == 2
    assert after["clinician_summary"] is None and after["reason"] is None  # staff-only


def test_failed_interpretation_is_marked(client, lab_setup):
    _, triage = lab_setup
    triage.error = RuntimeError("triage down")
    _upload(client)
    [report] = _reports(client, CLINICIAN)
    assert report["status"] == "failed" and report["results"] == []
    # a failed report can't be approved for the patient
    assert (
        client.patch(
            f"/lab-reports/{report['id']}", json={"patient_explanation": "x"}, headers=CLINICIAN
        ).status_code
        == 404
    )


# --- validation and access --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("file", "code"),
    [(("notes.txt", b"hello", "text/plain"), 415), (("empty.pdf", b"", "application/pdf"), 422)],
    ids=["wrong-type", "empty"],
)
def test_bad_files_are_rejected(client, lab_setup, file, code):
    assert _upload(client, file=file).status_code == code


def test_files_over_the_limit_are_rejected(client, lab_setup, monkeypatch):
    monkeypatch.setattr(labs, "MAX_BYTES", 10)
    assert (
        _upload(client, file=("big.pdf", b"%PDF" + b"x" * 20, "application/pdf")).status_code == 413
    )


def test_who_may_do_what(client, lab_setup):
    assert _upload(client, headers=OTHER).status_code == 404  # someone else's appointment
    assert _upload(client, headers=CLINICIAN).status_code == 403
    report_id = _upload(client).json()["id"]
    assert client.get("/appointments/1/lab-reports", headers=OTHER).status_code == 404
    assert (
        client.patch(
            f"/lab-reports/{report_id}", json={"patient_explanation": "x"}, headers=PATIENT
        ).status_code
        == 403
    )
    assert client.get(f"/lab-reports/{report_id}/file", headers=PATIENT).status_code == 403
    file = client.get(f"/lab-reports/{report_id}/file", headers=CLINICIAN)
    assert file.status_code == 200 and file.content == PDF[1]
    assert file.headers["cache-control"] == "no-store"


# --- combined urgency in the queue ------------------------------------------------------------


def _queue_entry(client):
    [entry] = client.get("/queue", headers=CLINICIAN).json()
    return entry


def test_a_critical_lab_makes_a_routine_patient_urgent(client, db, lab_setup):
    db.execute(
        "INSERT INTO triage_results (appointment_id, ai_urgency, summary) "
        "VALUES (1, 'routine', 'mild cough')"
    )
    _upload(client)
    entry = _queue_entry(client)
    assert entry["triage"]["urgency"] == "routine"
    assert entry["lab"]["urgency"] == "urgent"
    assert entry["lab"]["reason"] == "Critical: potassium 6.8 mmol/L"
    assert entry["urgency"] == "urgent"


def test_an_older_clinician_decision_cannot_hide_a_new_critical_lab(client, db, lab_setup):
    db.execute(
        "INSERT INTO triage_results (appointment_id, ai_urgency, summary, final_urgency, "
        "reviewed_at) VALUES (1, 'soon', 's', 'routine', now() - interval '1 hour')"
    )
    _upload(client)
    assert _queue_entry(client)["urgency"] == "urgent"


def test_a_clinician_reviewing_after_the_lab_has_the_final_say(client, db, lab_setup):
    db.execute(
        "INSERT INTO triage_results (appointment_id, ai_urgency, summary) "
        "VALUES (1, 'routine', 's')"
    )
    _upload(client)
    client.patch("/triage/1", json={"final_urgency": "soon"}, headers=CLINICIAN)
    assert _queue_entry(client)["urgency"] == "soon"


def test_a_lab_alone_puts_the_patient_in_the_queue_order(client, lab_setup):
    _, triage = lab_setup
    triage.result = _interpretation(urgency="soon", reason="Abnormal: glucose 201.8 mg/dL (high)")
    _upload(client)
    entry = _queue_entry(client)
    assert entry["triage"] is None and entry["urgency"] == "soon"


def test_metrics_count_lab_uploads(client, lab_setup):
    _upload(client)
    text = client.get("/metrics").text
    assert 'lab_uploads_total{content_type="application/pdf",role="patient"}' in text
    assert 'lab_reports_processed_total{status="ready"}' in text


# --- lab technicians: worklist and upload -----------------------------------------------------

DAY = "2030-01-07"


def _book(db, patient_id, starts_at, status="booked"):
    """Another slot with a booking; returns the appointment id."""
    slot = db.execute(
        "INSERT INTO slots (provider_id, starts_at, ends_at) "
        "VALUES (1, %s, %s::timestamptz + interval '30 minutes') RETURNING id",
        (starts_at, starts_at),
    ).fetchone()[0]
    return db.execute(
        "INSERT INTO appointments (patient_id, slot_id, status) VALUES (%s, %s, %s) RETURNING id",
        (patient_id, slot, status),
    ).fetchone()[0]


def _tech_upload(client, appointment=1, headers=LAB_TECH, file=PDF):
    return client.post(
        f"/lab/appointments/{appointment}/reports", files={"file": file}, headers=headers
    )


def test_a_lab_tech_uploads_for_another_patient_and_the_report_is_read(client, db, lab_setup):
    store, triage = lab_setup
    response = _tech_upload(client)  # appointment 1 belongs to patient 1
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "processing" and body["results"] == []
    assert triage.calls == [(PDF[1], "application/pdf")]
    assert len(list(store.folder.rglob("*.pdf"))) == 1
    assert db.execute("SELECT uploaded_by FROM lab_reports").fetchone()[0] == 4
    # Read in the background, like a patient's upload, and the queue updates the same way
    [report] = _reports(client, CLINICIAN)
    assert report["status"] == "ready" and report["lab_urgency"] == "urgent"
    assert _queue_entry(client)["urgency"] == "urgent"


def test_the_uploader_is_saved_for_patients_too(client, db, lab_setup):
    _upload(client)
    assert db.execute("SELECT uploaded_by FROM lab_reports").fetchone()[0] == 1


def test_worklist_lists_scheduled_visits_without_clinical_data(client, db, lab_setup):
    checked_in = _book(db, 2, "2030-01-07 10:00+00", "checked_in")
    _book(db, 2, "2030-01-07 11:00+00", "cancelled")
    _book(db, 2, "2030-01-07 12:00+00", "completed")
    _book(db, 2, "2030-01-08 09:00+00")  # another day
    db.execute(
        "INSERT INTO triage_results (appointment_id, ai_urgency, summary) "
        "VALUES (1, 'urgent', 'chest pain')"
    )
    _tech_upload(client)

    response = client.get(f"/lab/worklist?date={DAY}", headers=LAB_TECH)
    assert response.status_code == 200
    first, second = response.json()
    assert [first["appointment_id"], second["appointment_id"]] == [1, checked_in]
    assert first["patient_label"] == "Patient 0001" and second["patient_label"] == "Patient 0002"
    assert first["provider_name"] == "Dr. One" and first["status"] == "booked"
    assert second["status"] == "checked_in" and second["reports"] == []
    [report] = first["reports"]
    assert set(report) == {"id", "status", "uploaded_at", "lab_urgency", "reason"}
    assert report["status"] == "ready" and report["lab_urgency"] == "urgent"
    # Who, when and with whom: nothing else. No symptoms, triage, names or emails.
    assert set(first) == {
        "appointment_id",
        "patient_label",
        "starts_at",
        "provider_name",
        "status",
        "reports",
    }
    assert "chest pain" not in response.text and "example.com" not in response.text


def test_worklist_defaults_to_today_and_can_be_empty(client, lab_setup):
    assert client.get("/lab/worklist", headers=LAB_TECH).json() == []  # nothing booked today
    assert client.get("/lab/worklist?date=2030-02-01", headers=LAB_TECH).json() == []
    assert client.get("/lab/worklist?date=nope", headers=LAB_TECH).status_code == 422


def test_admins_can_use_the_lab_routes_too(client, lab_setup):
    admin = as_user(5, role="admin", email="admin@example.com")
    assert client.get(f"/lab/worklist?date={DAY}", headers=admin).status_code == 200


def test_only_lab_techs_use_the_lab_routes(client, lab_setup):
    for headers in (PATIENT, OTHER, CLINICIAN):
        assert client.get(f"/lab/worklist?date={DAY}", headers=headers).status_code == 403
        assert _tech_upload(client, headers=headers).status_code == 403
    assert client.get(f"/lab/worklist?date={DAY}").status_code == 401
    assert _tech_upload(client, headers={}).status_code == 401


def test_a_lab_tech_cannot_read_clinical_data(client, lab_setup):
    report_id = _tech_upload(client).json()["id"]
    assert client.get("/queue", headers=LAB_TECH).status_code == 403
    assert client.get("/appointments/1/lab-reports", headers=LAB_TECH).status_code == 403
    assert client.get(f"/lab-reports/{report_id}/file", headers=LAB_TECH).status_code == 403
    approve = client.patch(
        f"/lab-reports/{report_id}", json={"patient_explanation": "x"}, headers=LAB_TECH
    )
    assert approve.status_code == 403
    assert (
        client.patch("/triage/1", json={"final_urgency": "routine"}, headers=LAB_TECH).status_code
        == 403
    )


def test_the_lab_tech_upload_response_has_no_results(client, lab_setup):
    # Even though the report is read in the background, the response only confirms receipt
    body = _tech_upload(client).json()
    assert body["lab_urgency"] is None and body["clinician_summary"] is None
    assert body["patient_explanation"] is None and body["results"] == []


@pytest.mark.parametrize(
    ("status", "code"),
    [("booked", 202), ("checked_in", 202), ("cancelled", 409), ("completed", 409)],
)
def test_lab_techs_upload_only_for_scheduled_visits(client, db, lab_setup, status, code):
    appointment = _book(db, 2, "2030-01-07 10:00+00", status)
    assert _tech_upload(client, appointment=appointment).status_code == code


def test_lab_tech_upload_for_an_unknown_appointment_is_404(client, lab_setup):
    assert _tech_upload(client, appointment=999).status_code == 404


@pytest.mark.parametrize(
    ("file", "code"),
    [
        (("notes.txt", b"hello", "text/plain"), 415),
        (("empty.pdf", b"", "application/pdf"), 422),
    ],
)
def test_lab_tech_uploads_check_the_file(client, lab_setup, file, code):
    assert _tech_upload(client, file=file).status_code == code


def test_lab_tech_uploads_are_limited_to_10_mb(client, lab_setup, monkeypatch):
    monkeypatch.setattr(labs, "MAX_BYTES", 10)
    big = ("big.pdf", b"%PDF" + b"x" * 20, "application/pdf")
    assert _tech_upload(client, file=big).status_code == 413


def test_patient_uploads_still_work_on_their_own_appointment_only(client, db, lab_setup):
    # Unchanged by the lab tech route: someone else's appointment is a 404 for a patient
    assert _upload(client, headers=OTHER).status_code == 404
    assert _upload(client).status_code == 202


def test_metrics_count_uploads_by_role(client, lab_setup):
    _upload(client)
    _tech_upload(client)
    text = client.get("/metrics").text
    assert 'lab_uploads_total{content_type="application/pdf",role="patient"}' in text
    assert 'lab_uploads_total{content_type="application/pdf",role="lab_tech"}' in text


def test_the_migration_fills_in_the_uploader_of_older_reports_and_can_run_twice(db, lab_setup):
    migration = (DB_DIR / "schemav4_lab_uploaded_by.sql").read_text()
    db.execute(
        "INSERT INTO lab_reports (appointment_id, blob_name, content_type, size_bytes) "
        "VALUES (1, 'old/report.pdf', 'application/pdf', 10)"
    )
    assert db.execute("SELECT uploaded_by FROM lab_reports").fetchone()[0] is None
    db.execute(migration)
    db.execute(migration)
    assert db.execute("SELECT uploaded_by FROM lab_reports").fetchone()[0] == 1  # the patient
