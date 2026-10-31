from contextlib import contextmanager

import pytest
from psycopg.rows import dict_row

from app import db as app_db
from app import labs
from app.storage import LocalStore, get_store
from app.triage import get_triage_client
from tests.conftest import _connect, as_user

PATIENT = as_user(1, email="p1@example.com")
OTHER = as_user(2, email="p2@example.com")
CLINICIAN = as_user(3, role="clinician", email="doc@example.com")
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
    """Patients 1 and 2, clinician 3; patient 1 has appointment 1. Local file store in tmp."""
    from app.main import app

    db.execute(
        "INSERT INTO users (email, role) VALUES ('p1@example.com', 'patient'), "
        "('p2@example.com', 'patient'), ('doc@example.com', 'clinician')"
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
    assert 'lab_uploads_total{content_type="application/pdf"}' in text
    assert 'lab_reports_processed_total{status="ready"}' in text
