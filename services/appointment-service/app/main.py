from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from psycopg import errors

from app import db
from app.models import (
    Appointment,
    AppointmentCreate,
    IntakeCreate,
    QueueEntry,
    Slot,
    TriageRecord,
    TriageReview,
)
from app.queue import TRIAGE_COLUMNS, load_queue, queue_events
from app.triage import TriageServiceClient, get_triage_client


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    db.open_pool()
    yield
    db.close_pool()


app = FastAPI(title="Appointment Service", version="0.1.0", lifespan=lifespan)

Conn = Annotated[psycopg.Connection, Depends(db.get_conn)]
Triage = Annotated[TriageServiceClient, Depends(get_triage_client)]


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check used by docker-compose, Kubernetes probes, and CI."""
    return {"status": "ok", "service": "appointment-service"}


@app.get("/slots")
def list_slots(
    conn: Conn,
    day: Annotated[date, Query(alias="date", description="Day to search, YYYY-MM-DD (UTC)")],
    provider_id: Annotated[int | None, Query(gt=0)] = None,
) -> list[Slot]:
    """Free, upcoming slots that start on the given day, earliest first.

    A slot is free if it has no appointment, or only cancelled ones.
    """
    start = datetime.combine(day, time.min, tzinfo=UTC)
    rows = conn.execute(
        """
        SELECT s.id, s.provider_id, s.starts_at, s.ends_at
        FROM slots s
        LEFT JOIN appointments a ON a.slot_id = s.id AND a.status <> 'cancelled'
        WHERE a.id IS NULL
          AND s.starts_at >= %(start)s AND s.starts_at < %(end)s
          AND s.starts_at > now()
          AND (%(provider_id)s::bigint IS NULL OR s.provider_id = %(provider_id)s)
        ORDER BY s.starts_at, s.provider_id
        """,
        {"start": start, "end": start + timedelta(days=1), "provider_id": provider_id},
    ).fetchall()
    return [Slot(**row) for row in rows]


@app.post("/appointments", status_code=status.HTTP_201_CREATED)
def book_appointment(conn: Conn, body: AppointmentCreate) -> Appointment:
    """Book a slot. Returns 409 if it is already booked or has already started."""
    try:
        with conn.transaction():
            slot = conn.execute(
                "SELECT starts_at > now() AS upcoming FROM slots WHERE id = %s", (body.slot_id,)
            ).fetchone()
            if slot is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Slot not found")
            if not slot["upcoming"]:
                raise HTTPException(status.HTTP_409_CONFLICT, "Slot has already started")
            patient = conn.execute(
                "SELECT 1 FROM users WHERE id = %s AND role = 'patient'", (body.patient_id,)
            ).fetchone()
            if patient is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found")
            row = conn.execute(
                """
                INSERT INTO appointments (patient_id, slot_id) VALUES (%s, %s)
                RETURNING id, patient_id, slot_id, status, created_at
                """,
                (body.patient_id, body.slot_id),
            ).fetchone()
    except errors.UniqueViolation as exc:
        # The unique index on active appointments catches double booking, even concurrent ones.
        raise HTTPException(status.HTTP_409_CONFLICT, "Slot is already booked") from exc
    return Appointment(**row)


@app.post("/intake", status_code=status.HTTP_201_CREATED)
def submit_intake(conn: Conn, triage: Triage, body: IntakeCreate) -> TriageRecord:
    """Send the symptoms to the triage service and store its result for the clinician.

    Only the structured result is stored. The symptom text is never written to the database.
    """
    appointment = conn.execute(
        "SELECT a.status, t.id AS triage_id FROM appointments a "
        "LEFT JOIN triage_results t ON t.appointment_id = a.id WHERE a.id = %s",
        (body.appointment_id,),
    ).fetchone()
    if appointment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
    if appointment["status"] == "cancelled":
        raise HTTPException(status.HTTP_409_CONFLICT, "Appointment is cancelled")
    if appointment["triage_id"] is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Intake already submitted")

    assessment, latency_ms = triage.assess(body.symptoms)
    try:
        with conn.transaction():
            row = conn.execute(
                f"""
                INSERT INTO triage_results AS t
                    (appointment_id, ai_urgency, suggested_specialty, red_flags, summary,
                     latency_ms)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING {TRIAGE_COLUMNS}
                """,
                (
                    body.appointment_id,
                    assessment.urgency,
                    assessment.suggested_specialty,
                    assessment.red_flags,
                    assessment.summary,
                    latency_ms,
                ),
            ).fetchone()
    except errors.UniqueViolation as exc:
        # Two intakes for the same appointment raced each other
        raise HTTPException(status.HTTP_409_CONFLICT, "Intake already submitted") from exc
    return TriageRecord.model_validate(row)


@app.get("/queue")
def get_queue(conn: Conn) -> list[QueueEntry]:
    """Waiting patients, most urgent first."""
    return load_queue(conn)


@app.get("/queue/stream", response_class=StreamingResponse)
async def stream_queue(
    request: Request, connect: Annotated[object, Depends(db.get_async_connect)]
) -> StreamingResponse:
    """Server-Sent Events. Sends the whole queue on connect and again after every change."""
    return StreamingResponse(
        queue_events(connect, request.is_disconnected),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.patch("/triage/{triage_id}")
def review_triage(conn: Conn, triage_id: int, body: TriageReview) -> TriageRecord:
    """Clinician accepts (same urgency) or overrides (different urgency) the AI suggestion."""
    row = conn.execute(
        f"""
        UPDATE triage_results AS t
        SET final_urgency = %(final)s, overridden = (%(final)s <> t.ai_urgency),
            reviewed_at = now()
        WHERE t.id = %(id)s
        RETURNING {TRIAGE_COLUMNS}
        """,
        {"final": body.final_urgency, "id": triage_id},
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Triage result not found")
    return TriageRecord.model_validate(row)


# TODO (Backend A): auth (JWT roles: patient, clinician, admin). See docs/api.md.
