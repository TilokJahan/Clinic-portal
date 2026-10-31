import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from psycopg import errors

from app import db, metrics
from app.auth import (
    AnyUser,
    Clinician,
    CurrentUser,
    Patient,
    auth_mode,
    issue_dev_token,
    stream_clinician,
)
from app.models import (
    Appointment,
    AppointmentCreate,
    DevLogin,
    IntakeCreate,
    MyAppointment,
    QueueEntry,
    Slot,
    TokenResponse,
    TriageRecord,
    TriageReview,
    UserOut,
)
from app.queue import TRIAGE_COLUMNS, load_queue, queue_events
from app.triage import TriageServiceClient, get_triage_client


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    db.open_pool()
    yield
    db.close_pool()


app = FastAPI(title="Appointment Service", version="0.1.0", lifespan=lifespan)
metrics.install(app)

# The frontend on Azure Static Web Apps calls the API on another origin. List the allowed
# origins (comma separated) in CORS_ALLOWED_ORIGINS; empty means same-origin only (compose/nginx).
_origins = [o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Authorization", "Content-Type"],
    )

Conn = Annotated[psycopg.Connection, Depends(db.get_conn)]
Triage = Annotated[TriageServiceClient, Depends(get_triage_client)]


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check used by docker-compose, Kubernetes probes, and CI."""
    return {"status": "ok", "service": "appointment-service"}


@app.get("/ready")
def ready(conn: Conn) -> dict[str, str]:
    """Readiness probe: only take traffic when the database answers."""
    conn.execute("SELECT 1")
    return {"status": "ready"}


@app.post("/auth/dev-login")
def dev_login(conn: Conn, body: DevLogin) -> TokenResponse:
    """Demo sign-in for the synthetic seed users. Only exists when AUTH_MODE=dev."""
    if auth_mode() != "dev":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    row = conn.execute(
        "SELECT id, email, role FROM users WHERE email = %s", (body.email.strip().lower(),)
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown demo account")
    user = CurrentUser(**row)
    return TokenResponse(access_token=issue_dev_token(user), user=UserOut(**row))


@app.get("/me")
def me(user: AnyUser) -> UserOut:
    return UserOut(id=user.id, email=user.email, role=user.role)


@app.get("/slots")
def list_slots(
    conn: Conn,
    _: AnyUser,
    day: Annotated[date, Query(alias="date", description="Day to search, YYYY-MM-DD (UTC)")],
    provider_id: Annotated[int | None, Query(gt=0)] = None,
) -> list[Slot]:
    """Free, upcoming slots that start on the given day, earliest first.

    A slot is free if it has no appointment, or only cancelled ones.
    """
    start = datetime.combine(day, time.min, tzinfo=UTC)
    rows = conn.execute(
        """
        SELECT s.id, s.provider_id, p.name AS provider_name, p.specialty, s.starts_at, s.ends_at
        FROM slots s
        JOIN providers p ON p.id = s.provider_id
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


@app.get("/appointments")
def my_appointments(conn: Conn, user: Patient) -> list[MyAppointment]:
    """The signed-in patient's bookings that aren't cancelled, soonest first."""
    rows = conn.execute(
        """
        SELECT a.id, a.slot_id, a.status, a.created_at, s.starts_at,
               p.name AS provider_name, p.specialty, t.id IS NOT NULL AS intake_submitted
        FROM appointments a
        JOIN slots s ON s.id = a.slot_id
        JOIN providers p ON p.id = s.provider_id
        LEFT JOIN triage_results t ON t.appointment_id = a.id
        WHERE a.patient_id = %s AND a.status <> 'cancelled'
        ORDER BY s.starts_at
        """,
        (user.id,),
    ).fetchall()
    return [MyAppointment(**row) for row in rows]


@app.post("/appointments", status_code=status.HTTP_201_CREATED)
def book_appointment(conn: Conn, user: Patient, body: AppointmentCreate) -> Appointment:
    """Book a slot for the signed-in patient. 409 if it is already booked or has started."""
    try:
        with conn.transaction():
            slot = conn.execute(
                "SELECT starts_at > now() AS upcoming FROM slots WHERE id = %s", (body.slot_id,)
            ).fetchone()
            if slot is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Slot not found")
            if not slot["upcoming"]:
                metrics.BOOKING_CONFLICTS.labels("started").inc()
                raise HTTPException(status.HTTP_409_CONFLICT, "Slot has already started")
            row = conn.execute(
                """
                INSERT INTO appointments (patient_id, slot_id) VALUES (%s, %s)
                RETURNING id, patient_id, slot_id, status, created_at
                """,
                (user.id, body.slot_id),
            ).fetchone()
    except errors.UniqueViolation as exc:
        # The unique index on active appointments catches double booking, even concurrent ones.
        metrics.BOOKING_CONFLICTS.labels("already_booked").inc()
        raise HTTPException(status.HTTP_409_CONFLICT, "Slot is already booked") from exc
    except errors.ForeignKeyViolation as exc:
        # A valid token for a user that has since been removed
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user") from exc
    metrics.BOOKINGS.inc()
    return Appointment(**row)


@app.post("/intake", status_code=status.HTTP_201_CREATED)
def submit_intake(conn: Conn, user: Patient, triage: Triage, body: IntakeCreate) -> TriageRecord:
    """Send the symptoms to the triage service and store its result for the clinician.

    Only the structured result is stored. The symptom text is never written to the database.
    """
    appointment = conn.execute(
        "SELECT a.status, t.id AS triage_id FROM appointments a "
        "LEFT JOIN triage_results t ON t.appointment_id = a.id "
        "WHERE a.id = %s AND a.patient_id = %s",
        (body.appointment_id, user.id),
    ).fetchone()
    if appointment is None:  # also when it belongs to someone else: don't reveal it exists
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
    if appointment["status"] == "cancelled":
        raise HTTPException(status.HTTP_409_CONFLICT, "Appointment is cancelled")
    if appointment["triage_id"] is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Intake already submitted")

    assessment, latency_ms = triage.assess(body.symptoms)
    metrics.TRIAGE_CALL_SECONDS.observe(latency_ms / 1000)
    if assessment.fallback:
        metrics.TRIAGE_FALLBACKS.inc()
    try:
        with conn.transaction():
            row = conn.execute(
                f"""
                INSERT INTO triage_results AS t
                    (appointment_id, ai_urgency, suggested_specialty, red_flags, summary,
                     latency_ms, tokens_used)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING {TRIAGE_COLUMNS}
                """,
                (
                    body.appointment_id,
                    assessment.urgency,
                    assessment.suggested_specialty,
                    assessment.red_flags,
                    assessment.summary,
                    latency_ms,
                    assessment.tokens_used,
                ),
            ).fetchone()
    except errors.UniqueViolation as exc:
        # Two intakes for the same appointment raced each other
        raise HTTPException(status.HTTP_409_CONFLICT, "Intake already submitted") from exc
    metrics.INTAKES.labels(assessment.urgency.value).inc()
    return TriageRecord.model_validate(row)


@app.get("/queue")
def get_queue(conn: Conn, _: Clinician) -> list[QueueEntry]:
    """Waiting patients, most urgent first."""
    return load_queue(conn)


@app.get("/queue/stream", response_class=StreamingResponse)
async def stream_queue(
    request: Request,
    connect: Annotated[object, Depends(db.get_async_connect)],
    _: Annotated[CurrentUser, Depends(stream_clinician)],
) -> StreamingResponse:
    """Server-Sent Events. Sends the whole queue on connect and again after every change."""
    return StreamingResponse(
        queue_events(connect, request.is_disconnected),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.patch("/triage/{triage_id}")
def review_triage(conn: Conn, user: Clinician, triage_id: int, body: TriageReview) -> TriageRecord:
    """Clinician accepts (same urgency) or overrides (different urgency) the AI suggestion."""
    row = conn.execute(
        f"""
        UPDATE triage_results AS t
        SET final_urgency = %(final)s, overridden = (%(final)s <> t.ai_urgency),
            reviewed_at = now(), reviewed_by = %(user)s
        WHERE t.id = %(id)s
        RETURNING {TRIAGE_COLUMNS}
        """,
        {"final": body.final_urgency, "id": triage_id, "user": user.id},
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Triage result not found")
    metrics.REVIEWS.labels("overridden" if row["overridden"] else "accepted").inc()
    return TriageRecord.model_validate(row)
