import time
from contextlib import contextmanager

import jwt
import pytest
from psycopg.rows import dict_row

from app import auth
from tests.conftest import _connect, as_user


@pytest.fixture
def people(db):
    """Patients 1 and 2, clinician 3, one slot booked by patient 1 (appointment 1)."""
    db.execute(
        "INSERT INTO users (email, role) VALUES ('p1@example.com', 'patient'), "
        "('p2@example.com', 'patient'), ('doc@example.com', 'clinician')"
    )
    db.execute("INSERT INTO providers (name, specialty) VALUES ('Dr. One', 'General Practice')")
    db.execute(
        "INSERT INTO slots (provider_id, starts_at, ends_at) VALUES "
        "(1, '2030-01-07 09:00+00', '2030-01-07 09:30+00'), "
        "(1, '2030-01-08 09:00+00', '2030-01-08 09:30+00')"
    )
    db.execute("INSERT INTO appointments (patient_id, slot_id) VALUES (1, 1)")


PATIENT = as_user(1, email="p1@example.com")
OTHER_PATIENT = as_user(2, email="p2@example.com")
CLINICIAN = as_user(3, role="clinician", email="doc@example.com")


# --- dev login ------------------------------------------------------------------------------


def test_dev_login_returns_a_token_that_works(client, people):
    response = client.post("/auth/dev-login", json={"email": "DOC@example.com "})
    assert response.status_code == 200
    body = response.json()
    assert body["user"] == {"id": 3, "email": "doc@example.com", "role": "clinician"}
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    assert client.get("/me", headers=headers).json()["role"] == "clinician"


def test_dev_login_unknown_account(client, people):
    assert client.post("/auth/dev-login", json={"email": "who@example.com"}).status_code == 401


def test_dev_login_does_not_exist_outside_dev_mode(client, people, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "identity-platform")
    assert client.post("/auth/dev-login", json={"email": "p1@example.com"}).status_code == 404


# --- tokens ---------------------------------------------------------------------------------


def _token(secret="test-secret-for-pytest-only", **overrides):
    claims = {"sub": "1", "email": "p1@example.com", "role": "patient", "exp": time.time() + 60}
    return {"Authorization": "Bearer " + jwt.encode(claims | overrides, secret, "HS256")}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer not-a-jwt"},
        _token(secret="some-other-secret-value"),
        _token(exp=time.time() - 10),
    ],
    ids=["missing", "garbage", "wrong-signature", "expired"],
)
def test_bad_or_missing_tokens_get_401(client, people, headers):
    response = client.get("/me", headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


# --- roles ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/queue", None),
        ("patch", "/triage/1", {"final_urgency": "soon"}),
    ],
)
def test_patients_cannot_use_clinician_endpoints(client, people, method, path, body):
    kwargs = {"json": body} if body else {}
    assert getattr(client, method)(path, headers=PATIENT, **kwargs).status_code == 403


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/appointments", {"slot_id": 2}),
        ("get", "/appointments", None),
        ("post", "/intake", {"appointment_id": 1, "symptoms": "cough"}),
    ],
)
def test_clinicians_cannot_use_patient_endpoints(client, people, method, path, body):
    kwargs = {"json": body} if body else {}
    assert getattr(client, method)(path, headers=CLINICIAN, **kwargs).status_code == 403


def test_everyone_signed_in_can_see_slots(client, people):
    for headers in (PATIENT, CLINICIAN):
        assert (
            client.get("/slots", params={"date": "2030-01-08"}, headers=headers).status_code == 200
        )
    assert client.get("/slots", params={"date": "2030-01-08"}).status_code == 401


# --- ownership ------------------------------------------------------------------------------


def test_patients_only_see_their_own_appointments(client, people):
    mine = client.get("/appointments", headers=PATIENT).json()
    assert [(a["id"], a["provider_name"], a["intake_submitted"]) for a in mine] == [
        (1, "Dr. One", False)
    ]
    assert client.get("/appointments", headers=OTHER_PATIENT).json() == []


def test_intake_for_someone_elses_appointment_looks_like_not_found(client, people):
    response = client.post(
        "/intake", json={"appointment_id": 1, "symptoms": "cough"}, headers=OTHER_PATIENT
    )
    assert response.status_code == 404


def test_review_records_which_clinician_decided(client, people, db):
    db.execute(
        "INSERT INTO triage_results (appointment_id, ai_urgency, summary) "
        "VALUES (1, 'urgent', 's')"
    )
    response = client.patch("/triage/1", json={"final_urgency": "soon"}, headers=CLINICIAN)
    assert response.status_code == 200
    assert db.execute("SELECT reviewed_by FROM triage_results").fetchone()[0] == 3


# --- live stream ----------------------------------------------------------------------------


@pytest.fixture
def stream_db(database_url, monkeypatch):
    """The stream looks users up on a short-lived connection; point it at the test schema."""

    @contextmanager
    def connection():
        with _connect(database_url) as conn:
            conn.row_factory = dict_row
            yield conn

    monkeypatch.setattr(auth.db, "connection", connection)


def test_stream_needs_a_clinician(client, people, stream_db):
    assert client.get("/queue/stream").status_code == 401
    token = PATIENT["Authorization"].removeprefix("Bearer ")
    assert client.get("/queue/stream", params={"access_token": token}).status_code == 403


# --- identity platform ----------------------------------------------------------------------


def test_identity_platform_user_is_created_as_patient_on_first_sign_in(people, db, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "identity-platform")
    claims = {"email": "New.Person@example.com", "email_verified": True}
    monkeypatch.setattr(auth, "_verify_identity_platform", lambda token: claims)
    db.row_factory = dict_row
    user = auth.decode("any", db)
    assert (user.email, user.role) == ("new.person@example.com", "patient")
    # Signing in again finds the same user
    assert auth.decode("any", db).id == user.id


def test_identity_platform_rejects_unverified_email(people, db, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "identity-platform")
    monkeypatch.setattr(
        auth,
        "_verify_identity_platform",
        lambda t: {"email": "x@example.com", "email_verified": False},
    )
    with pytest.raises(auth.HTTPException) as exc:
        auth.decode("any", db)
    assert exc.value.status_code == 401


def test_identity_platform_keeps_an_existing_role(people, db, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "identity-platform")
    # A token claiming admin can't upgrade an existing clinician
    claims = {"email": "doc@example.com", "email_verified": True, "role": "admin"}
    monkeypatch.setattr(auth, "_verify_identity_platform", lambda token: claims)
    db.row_factory = dict_row
    assert auth.decode("any", db).role == "clinician"
