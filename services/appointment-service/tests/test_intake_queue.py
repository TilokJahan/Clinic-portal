import asyncio
import json
import sys

import httpx
import psycopg
import pytest
from psycopg.rows import dict_row

from app.models import TriageAssessment, Urgency
from app.queue import queue_events
from app.triage import FALLBACK, TriageServiceClient, get_triage_client
from tests.conftest import TEST_SCHEMA, as_user

if sys.platform == "win32":  # psycopg's async mode needs the selector event loop on Windows
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class FakeTriage:
    """Stands in for the triage service: urgency depends on a keyword, like the real fake."""

    def __init__(self):
        self.calls: list[str] = []

    def assess(self, symptoms: str) -> tuple[TriageAssessment, int]:
        self.calls.append(symptoms)
        urgent = "chest pain" in symptoms
        return (
            TriageAssessment(
                urgency=Urgency.URGENT if urgent else Urgency.ROUTINE,
                suggested_specialty="Emergency Medicine" if urgent else "General Practice",
                red_flags=["chest pain"] if urgent else [],
                summary="Test summary.",
            ),
            12,
        )


@pytest.fixture
def triage(client):
    from app.main import app

    fake = FakeTriage()
    app.dependency_overrides[get_triage_client] = lambda: fake
    return fake


@pytest.fixture
def booked(client, db):
    """Three patients, each with a booked appointment (ids 1, 2, 3) on slots 1, 2, 3."""
    db.execute("INSERT INTO providers (name, specialty) VALUES ('Dr. One', 'General Practice')")
    db.execute(
        "INSERT INTO users (email, role) VALUES ('p1@example.com', 'patient'), "
        "('p2@example.com', 'patient'), ('p3@example.com', 'patient'), "
        "('doc@example.com', 'clinician')"
    )
    db.execute(
        """
        INSERT INTO slots (provider_id, starts_at, ends_at) VALUES
            (1, '2030-01-07 09:00+00', '2030-01-07 09:30+00'),
            (1, '2030-01-07 09:30+00', '2030-01-07 10:00+00'),
            (1, '2030-01-07 10:00+00', '2030-01-07 10:30+00')
        """
    )
    for patient in (1, 2, 3):
        response = client.post("/appointments", json={"slot_id": patient}, headers=as_user(patient))
        assert response.status_code == 201


CLINICIAN = as_user(4, role="clinician", email="doc@example.com")


def _intake(client, appointment_id: int, symptoms: str, patient: int | None = None):
    """Appointment n belongs to patient n in the `booked` fixture."""
    return client.post(
        "/intake",
        json={"appointment_id": appointment_id, "symptoms": symptoms},
        headers=as_user(patient or appointment_id),
    )


# --- POST /intake ---------------------------------------------------------------------------


def test_intake_stores_the_triage_result(client, db, booked, triage):
    response = _intake(client, 1, "I have chest pain")
    assert response.status_code == 201
    body = response.json()
    assert body["appointment_id"] == 1
    assert body["ai_urgency"] == body["urgency"] == "urgent"
    assert body["final_urgency"] is None and body["overridden"] is False
    assert body["red_flags"] == ["chest pain"]
    assert body["latency_ms"] == 12
    assert triage.calls == ["I have chest pain"]


def test_symptom_text_is_not_stored(client, db, booked, triage):
    _intake(client, 1, "unique-marker-text chest pain")
    dump = db.execute("SELECT to_jsonb(t)::text FROM triage_results t").fetchone()[0]
    assert "unique-marker-text" not in dump


def test_second_intake_for_the_same_appointment_returns_409(client, booked, triage):
    assert _intake(client, 1, "cough").status_code == 201
    response = _intake(client, 1, "cough again")
    assert response.status_code == 409
    assert response.json() == {"detail": "Intake already submitted"}


def test_intake_for_unknown_or_cancelled_appointment(client, db, booked, triage):
    assert _intake(client, 999, "cough").status_code == 404
    db.execute("UPDATE appointments SET status = 'cancelled' WHERE id = 2")
    response = _intake(client, 2, "cough")
    assert response.status_code == 409
    assert response.json() == {"detail": "Appointment is cancelled"}
    assert triage.calls == []  # the triage service is not called for invalid intakes


@pytest.mark.parametrize("body", [{"appointment_id": 1}, {"appointment_id": 1, "symptoms": ""}])
def test_intake_rejects_invalid_body(client, booked, triage, body):
    assert client.post("/intake", json=body, headers=as_user(1)).status_code == 422


# --- Triage service client ------------------------------------------------------------------


def _client_with(handler) -> TriageServiceClient:
    return TriageServiceClient("http://triage", transport=httpx.MockTransport(handler))


def test_triage_client_parses_the_service_response():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/triage"
        assert json.loads(request.content) == {"symptoms": "chest pain"}
        return httpx.Response(
            200,
            json={
                "urgency": "urgent",
                "suggested_specialty": "Emergency Medicine",
                "red_flags": ["chest pain"],
                "summary": "s",
            },
        )

    assessment, latency_ms = _client_with(handler).assess("chest pain")
    assert assessment.urgency == Urgency.URGENT
    assert latency_ms >= 0


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(500),
        lambda r: httpx.Response(200, json={"unexpected": True}),
        lambda r: httpx.Response(200, text="not json"),
        lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")),
    ],
    ids=["server-error", "wrong-shape", "not-json", "unreachable"],
)
def test_triage_client_falls_back_when_the_service_fails(handler):
    assessment, _ = _client_with(handler).assess("cough")
    assert assessment == FALLBACK
    assert assessment.urgency == Urgency.SOON


# --- GET /queue -----------------------------------------------------------------------------


def test_queue_is_sorted_by_urgency_then_intake_time(client, booked, triage):
    _intake(client, 1, "mild cough")  # routine
    _intake(client, 2, "chest pain")  # urgent
    queue = client.get("/queue", headers=CLINICIAN).json()
    assert [e["appointment_id"] for e in queue] == [2, 1, 3]  # 3 has no intake yet
    assert queue[0]["triage"]["urgency"] == "urgent"
    assert queue[2]["triage"] is None
    assert queue[0]["patient_label"] == "Patient 0002"
    assert queue[0]["provider_name"] == "Dr. One"
    assert "email" not in json.dumps(queue)


def test_queue_hides_cancelled_and_completed_appointments(client, db, booked):
    db.execute("UPDATE appointments SET status = 'cancelled' WHERE id = 1")
    db.execute("UPDATE appointments SET status = 'completed' WHERE id = 2")
    assert [e["appointment_id"] for e in client.get("/queue", headers=CLINICIAN).json()] == [3]


# --- PATCH /triage/{id} ---------------------------------------------------------------------


def test_clinician_accepts_the_suggestion(client, booked, triage):
    triage_id = _intake(client, 1, "chest pain").json()["id"]
    response = client.patch(
        f"/triage/{triage_id}", json={"final_urgency": "urgent"}, headers=CLINICIAN
    )
    assert response.status_code == 200
    body = response.json()
    assert body["final_urgency"] == "urgent" and body["overridden"] is False
    assert body["reviewed_at"] is not None


def test_clinician_override_changes_the_queue_order(client, booked, triage):
    urgent_id = _intake(client, 1, "chest pain").json()["id"]
    _intake(client, 2, "mild cough")
    response = client.patch(
        f"/triage/{urgent_id}", json={"final_urgency": "routine"}, headers=CLINICIAN
    )
    body = response.json()
    assert body["ai_urgency"] == "urgent"
    assert body["final_urgency"] == body["urgency"] == "routine"
    assert body["overridden"] is True
    # Both routine now, so intake time decides: appointment 1 submitted first
    assert [e["appointment_id"] for e in client.get("/queue", headers=CLINICIAN).json()] == [
        1,
        2,
        3,
    ]


def test_review_unknown_or_invalid(client, booked, triage):
    assert (
        client.patch("/triage/999", json={"final_urgency": "soon"}, headers=CLINICIAN).status_code
        == 404
    )
    triage_id = _intake(client, 1, "cough").json()["id"]
    response = client.patch(
        f"/triage/{triage_id}", json={"final_urgency": "whenever"}, headers=CLINICIAN
    )
    assert response.status_code == 422


# --- GET /queue/stream ----------------------------------------------------------------------


def test_stream_sends_the_queue_then_an_update_after_a_change(database_url, booked):
    async def connect():
        return await psycopg.AsyncConnection.connect(
            database_url,
            autocommit=True,
            row_factory=dict_row,
            options=f"-c search_path={TEST_SCHEMA}",
        )

    async def never_disconnected():
        return False

    async def run():
        events = queue_events(connect, never_disconnected, heartbeat_seconds=5)
        first = await anext(events)
        # Another connection changes the queue; the trigger sends a NOTIFY
        async with await connect() as other:
            await other.execute(
                "INSERT INTO triage_results (appointment_id, ai_urgency, summary) "
                "VALUES (3, 'urgent', 'from another replica')"
            )
        second = await asyncio.wait_for(anext(events), timeout=5)
        await events.aclose()
        return first, second

    first, second = asyncio.run(run())
    assert first.startswith("event: queue\ndata: ")
    initial = json.loads(first.split("data: ", 1)[1])
    assert [e["triage"] for e in initial] == [None, None, None]
    updated = json.loads(second.split("data: ", 1)[1])
    assert updated[0]["appointment_id"] == 3
    assert updated[0]["triage"]["urgency"] == "urgent"


def test_stream_sends_keep_alive_when_idle(database_url, booked):
    async def connect():
        return await psycopg.AsyncConnection.connect(
            database_url,
            autocommit=True,
            row_factory=dict_row,
            options=f"-c search_path={TEST_SCHEMA}",
        )

    async def never_disconnected():
        return False

    async def run():
        events = queue_events(connect, never_disconnected, heartbeat_seconds=0.2)
        await anext(events)
        idle = await anext(events)
        await events.aclose()
        return idle

    assert asyncio.run(run()) == ": keep-alive\n\n"
