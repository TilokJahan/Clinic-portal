import time
from contextlib import contextmanager
from pathlib import Path

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg import errors
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


LAB_TECH_MIGRATION = Path(__file__).resolve().parent.parent / "db" / "schemav3_lab_tech.sql"


@pytest.fixture
def lab_tech(people, db):
    """Adds lab technician 4 (the people fixture has users 1-3)."""
    db.execute("INSERT INTO users (email, role) VALUES ('tech@example.com', 'lab_tech')")


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
    monkeypatch.setenv("AUTH_MODE", "entra-external-id")
    assert client.post("/auth/dev-login", json={"email": "p1@example.com"}).status_code == 404


def test_lab_tech_can_sign_in_with_dev_login(client, lab_tech):
    response = client.post("/auth/dev-login", json={"email": "tech@example.com"})
    assert response.status_code == 200
    body = response.json()
    assert body["user"] == {"id": 4, "email": "tech@example.com", "role": "lab_tech"}
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    assert client.get("/me", headers=headers).json()["role"] == "lab_tech"


# --- the LabTech dependency (used by the lab endpoints that come next) -----------------------


def _lab_only_client() -> TestClient:
    """A tiny app with one lab-tech-only route. Dev tokens are checked without the database."""
    app = FastAPI()

    @app.get("/lab-only")
    def lab_only(user: auth.LabTech):
        return {"role": user.role}

    def no_database():
        yield None

    app.dependency_overrides[auth.db.get_conn] = no_database
    return TestClient(app)


@pytest.mark.parametrize(
    ("role", "expected"),
    [("lab_tech", 200), ("admin", 200), ("clinician", 403), ("patient", 403)],
)
def test_lab_tech_routes_allow_lab_techs_and_admins_only(role, expected):
    headers = as_user(9, role=role, email=f"{role}@example.com")
    assert _lab_only_client().get("/lab-only", headers=headers).status_code == expected


def test_lab_tech_routes_need_a_token():
    assert _lab_only_client().get("/lab-only").status_code == 401


# --- the users.role column and the v3 migration ------------------------------------------------


def test_users_accept_lab_tech_but_not_unknown_roles(db):
    db.execute("INSERT INTO users (email, role) VALUES ('t@example.com', 'lab_tech')")
    with pytest.raises(errors.CheckViolation):
        db.execute("INSERT INTO users (email, role) VALUES ('x@example.com', 'janitor')")


def _demo_lab_techs(db) -> int:
    row = db.execute("SELECT count(*) FROM users WHERE email = 'labtech1@example.com'").fetchone()
    return row[0]


def test_migration_adds_the_demo_lab_tech_to_an_existing_database_once(db, people):
    db.execute(LAB_TECH_MIGRATION.read_text())
    db.execute(LAB_TECH_MIGRATION.read_text())  # safe to run again
    assert _demo_lab_techs(db) == 1
    role = db.execute("SELECT role FROM users WHERE email = 'labtech1@example.com'").fetchone()[0]
    assert role == "lab_tech"


def test_migration_leaves_a_brand_new_database_to_the_seed(db):
    """With no users yet, the migration adds none, so seed.sql keeps demo ids 1-5 unchanged."""
    db.execute(LAB_TECH_MIGRATION.read_text())
    assert _demo_lab_techs(db) == 0


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


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/queue", None),
        ("patch", "/triage/1", {"final_urgency": "soon"}),
        ("post", "/appointments", {"slot_id": 2}),
        ("get", "/appointments", None),
        ("post", "/intake", {"appointment_id": 1, "symptoms": "cough"}),
    ],
)
def test_lab_techs_cannot_use_patient_or_clinician_endpoints(client, lab_tech, method, path, body):
    headers = as_user(4, role="lab_tech", email="tech@example.com")
    kwargs = {"json": body} if body else {}
    assert getattr(client, method)(path, headers=headers, **kwargs).status_code == 403


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


# --- Entra External ID ----------------------------------------------------------------------


def _sign_in_as(monkeypatch, claims):
    monkeypatch.setenv("AUTH_MODE", "entra-external-id")
    monkeypatch.setattr(auth, "_verify_entra", lambda token: claims)


def test_external_user_is_created_as_patient_on_first_sign_in(people, db, monkeypatch):
    _sign_in_as(monkeypatch, {"email": "New.Person@example.com"})
    db.row_factory = dict_row
    user = auth.decode("any", db)
    assert (user.email, user.role) == ("new.person@example.com", "patient")
    assert auth.decode("any", db).id == user.id  # signing in again finds the same user


def test_email_can_come_from_preferred_username(people, db, monkeypatch):
    _sign_in_as(monkeypatch, {"preferred_username": "p1@example.com"})
    db.row_factory = dict_row
    assert auth.decode("any", db).id == 1


def test_token_without_an_email_is_rejected(people, db, monkeypatch):
    _sign_in_as(monkeypatch, {"name": "No Email"})
    with pytest.raises(auth.HTTPException) as exc:
        auth.decode("any", db)
    assert exc.value.status_code == 401


def test_a_token_cannot_change_an_existing_role(people, db, monkeypatch):
    _sign_in_as(monkeypatch, {"email": "doc@example.com", "role": "admin"})
    db.row_factory = dict_row
    assert auth.decode("any", db).role == "clinician"


def test_operator_lists_assign_staff_roles(people, db, monkeypatch):
    monkeypatch.setenv("CLINICIAN_EMAILS", "new.doc@example.com, p2@example.com")
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    db.row_factory = dict_row

    def role_of(email):
        _sign_in_as(monkeypatch, {"email": email})
        return auth.decode("any", db).role

    assert role_of("New.Doc@example.com") == "clinician"  # first sign-in
    assert role_of("p2@example.com") == "clinician"  # existing patient promoted by the list
    assert role_of("boss@example.com") == "admin"
    assert role_of("someone@example.com") == "patient"


def test_lab_tech_list_assigns_the_role_and_admin_and_clinician_outrank_it(people, db, monkeypatch):
    monkeypatch.setenv("LAB_TECH_EMAILS", "New.Tech@example.com, p2@example.com, doc@example.com")
    monkeypatch.setenv("CLINICIAN_EMAILS", "doc@example.com")
    monkeypatch.setenv("ADMIN_EMAILS", "p1@example.com, boss@example.com")
    db.row_factory = dict_row

    def role_of(email):
        _sign_in_as(monkeypatch, {"email": email})
        return auth.decode("any", db).role

    assert role_of("New.Tech@example.com") == "lab_tech"  # first sign-in
    assert role_of("p2@example.com") == "lab_tech"  # existing patient moved by the list
    assert role_of("doc@example.com") == "clinician"  # on both lists: clinician wins
    assert role_of("p1@example.com") == "admin"  # patient on the admin list
    assert role_of("someone@example.com") == "patient"


# Real signature checks with a locally generated key standing in for the tenant's keys

TENANT = "11111111-2222-3333-4444-555555555555"
CLIENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@pytest.fixture
def tenant_key(monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import rsa

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class Keys:
        def get_signing_key_from_jwt(self, token):
            return type("Key", (), {"key": private.public_key()})

    monkeypatch.setenv("ENTRA_TENANT_ID", TENANT)
    monkeypatch.setenv("ENTRA_TENANT_SUBDOMAIN", "clinicdemo")
    monkeypatch.setenv("ENTRA_CLIENT_ID", CLIENT)
    monkeypatch.setattr(auth, "_jwks_client", Keys())
    return private


def _entra_token(private, **overrides):
    claims = {
        "iss": f"https://{TENANT}.ciamlogin.com/{TENANT}/v2.0",
        "aud": CLIENT,
        "exp": int(time.time()) + 300,
        "email": "p1@example.com",
    } | overrides
    return jwt.encode(claims, private, algorithm="RS256")


def test_entra_token_with_correct_issuer_and_audience_is_accepted(tenant_key):
    assert auth._verify_entra(_entra_token(tenant_key))["email"] == "p1@example.com"


@pytest.mark.parametrize(
    "overrides",
    [{"aud": "someone-elses-app"}, {"iss": "https://evil.example.com/v2.0"}, {"exp": 1}],
    ids=["wrong-audience", "wrong-issuer", "expired"],
)
def test_entra_token_checks_audience_issuer_and_expiry(tenant_key, overrides):
    with pytest.raises(jwt.PyJWTError):
        auth._verify_entra(_entra_token(tenant_key, **overrides))


def test_entra_token_signed_by_another_key_is_rejected(tenant_key):
    from cryptography.hazmat.primitives.asymmetric import rsa

    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(jwt.PyJWTError):
        auth._verify_entra(_entra_token(other))
