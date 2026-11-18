import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from psycopg import errors

from app import (
    admin,
    approval,
    db,
    lab_visits,
    labs,
    metrics,
    physician,
    reschedule,
    scheduling,
    urgency,
)
from app.auth import (
    AnyUser,
    Clinician,
    CurrentUser,
    Patient,
    auth_mode,
    issue_dev_token,
    stream_clinician,
    stream_patient,
)
from app.lab_needs import suggested_tests
from app.models import (
    Appointment,
    AppointmentCreate,
    Assessment,
    AssessmentCreate,
    DevLogin,
    IntakeCreate,
    MyAppointment,
    QueueEntry,
    Slot,
    TokenResponse,
    TriageAssessment,
    TriageRecord,
    TriageReview,
    UserOut,
)
from app.queue import TRIAGE_COLUMNS, load_queue, queue_events
from app.reschedule import load_my_appointments, my_appointment_events
from app.triage import TriageServiceClient, get_triage_client
from app.urgency import OPEN_TO_ALL, RESERVED_MESSAGE


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    db.open_pool()
    yield
    db.close_pool()


app = FastAPI(title="Appointment Service", version="0.1.0", lifespan=lifespan)
metrics.install(app)
app.include_router(admin.router)
app.include_router(approval.router)
app.include_router(physician.router)
app.include_router(labs.router)
app.include_router(lab_visits.router)
app.include_router(reschedule.router)
app.include_router(scheduling.router)

# Only needed if the frontend is ever served from another origin (compose, kind and AKS are all
# same-origin through nginx). List allowed origins, comma separated, in CORS_ALLOWED_ORIGINS.
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
    """Demo sign-in for the synthetic seed users. Only exists when AUTH_MODE=dev.

    If DEMO_PASSCODE is set (the public demo site), the request must carry it. The check runs
    before the account lookup, so a wrong passcode never reveals which emails exist.
    """
    if auth_mode() != "dev":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    expected = os.environ.get("DEMO_PASSCODE", "")
    if expected and not secrets.compare_digest(body.passcode.encode(), expected.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong or missing demo passcode")
    row = conn.execute(
        "SELECT id, email, role, active FROM users WHERE email = %s",
        (body.email.strip().lower(),),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown demo account")
    if not row.pop("active"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account is disabled")
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
    include_booked: Annotated[
        bool, Query(description="Also list booked times, with available=false")
    ] = False,
    urgent: Annotated[bool, Query(description="List the urgent reserve as available")] = False,
) -> list[Slot]:
    """Free, upcoming slots that start on the given day, earliest first.

    A slot is free if it has no appointment, or only cancelled ones. The urgent reserve is only
    listed on its own day while no urgent patient is waiting (see app/urgency.py), or to an
    urgent patient (booking still checks their assessment). With include_booked, every upcoming
    slot of the day is listed and the ones that can't be chosen have available=false, so the
    patient sees the whole day.
    """
    start = datetime.combine(day, time.min, tzinfo=UTC)
    rows = conn.execute(
        f"""
        SELECT s.id, s.provider_id, p.name AS provider_name, p.specialty, s.starts_at, s.ends_at,
               NOT {OPEN_TO_ALL} AS reserved,
               a.id IS NULL AND (%(urgent)s OR {OPEN_TO_ALL}) AS available
        FROM slots s
        JOIN providers p ON p.id = s.provider_id
        LEFT JOIN appointments a ON a.slot_id = s.id AND a.status <> 'cancelled'
        WHERE s.starts_at >= %(start)s AND s.starts_at < %(end)s AND s.starts_at > now()
          AND (%(include_booked)s OR (a.id IS NULL AND (%(urgent)s OR {OPEN_TO_ALL})))
          AND (%(provider_id)s::bigint IS NULL OR s.provider_id = %(provider_id)s)
        ORDER BY s.starts_at, s.provider_id
        """,
        {
            "start": start,
            "end": start + timedelta(days=1),
            "provider_id": provider_id,
            "include_booked": include_booked,
            "urgent": urgent,
        },
    ).fetchall()
    return [Slot(**row) for row in rows]


@app.post("/assessments", status_code=status.HTTP_201_CREATED)
def create_assessment(
    conn: Conn, user: Patient, triage: Triage, body: AssessmentCreate
) -> Assessment:
    """Step 1 of booking: describe the symptoms first. The triage result decides how soon the
    patient should be seen, and so which times they may request (POST /appointments with
    assessment_id). Only the structured result is stored, never the symptom text."""
    assessment, latency_ms = _assess(triage, body.symptoms)
    with conn.transaction():
        row = _store_triage(
            conn, None, assessment, latency_ms, user.id, suggested_tests(body.symptoms)
        )
    record = TriageRecord.model_validate(row)
    return Assessment(triage=record, max_within_hours=urgency.max_within_hours(record.urgency))


@app.get("/appointments")
def my_appointments(conn: Conn, user: Patient) -> list[MyAppointment]:
    """The signed-in patient's bookings, soonest first (see load_my_appointments)."""
    return load_my_appointments(conn, user.id)


@app.get("/appointments/stream", response_class=StreamingResponse)
async def stream_my_appointments(
    request: Request,
    connect: Annotated[object, Depends(db.get_async_connect)],
    user: Annotated[CurrentUser, Depends(stream_patient)],
) -> StreamingResponse:
    """Server-Sent Events. Sends the patient's appointments on connect and again whenever they
    change, so an offer or a moved visit shows up without reloading the page."""
    return StreamingResponse(
        my_appointment_events(connect, request.is_disconnected, user.id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/appointments", status_code=status.HTTP_201_CREATED)
def book_appointment(
    conn: Conn, user: Patient, triage: Triage, body: AppointmentCreate
) -> Appointment:
    """Request a slot for the signed-in patient. 409 if it is already taken or has started.

    The slot is held at once, and the request waits for a clinician's approval. With symptoms,
    the triage service assesses them first, so the clinician sees the urgency with the request.
    """
    assessment = None
    if body.symptoms is not None and body.assessment_id is None:
        # Before the transaction: the AI call takes seconds and shouldn't hold a lock
        assessment, latency_ms = _assess(triage, body.symptoms)
    try:
        with conn.transaction():
            prior = None
            if body.assessment_id is not None:
                prior = conn.execute(
                    """
                    SELECT ai_urgency, created_at > now() - interval '1 day' AS fresh
                    FROM triage_results
                    WHERE id = %s AND patient_id = %s AND appointment_id IS NULL
                    FOR UPDATE
                    """,
                    (body.assessment_id, user.id),
                ).fetchone()
                if prior is None:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "Assessment not found")
                if not prior["fresh"]:
                    raise HTTPException(
                        status.HTTP_409_CONFLICT, "Please describe your symptoms again"
                    )
            priority = prior["ai_urgency"] if prior else None
            limit = urgency.max_within_hours(priority)
            slot = conn.execute(
                f"SELECT s.starts_at > now() AS upcoming, {OPEN_TO_ALL} AS open, "
                "s.starts_at <= now() + %s AS in_time FROM slots s WHERE s.id = %s",
                (timedelta(hours=limit), body.slot_id),
            ).fetchone()
            if slot is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Slot not found")
            if not slot["upcoming"]:
                metrics.BOOKING_CONFLICTS.labels("started").inc()
                raise HTTPException(status.HTTP_409_CONFLICT, "Slot has already started")
            if not slot["open"] and priority != "urgent":
                raise HTTPException(status.HTTP_409_CONFLICT, RESERVED_MESSAGE)
            # Within the priority's limit, unless nothing at all is free that soon: then the
            # first free time after it is allowed (and the queue flags the visit)
            if prior and not slot["in_time"]:
                if scheduling.free_slots(conn, limit, limit=1, urgent=priority == "urgent"):
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_ENTITY, scheduling.limit_message(limit)
                    )
            row = conn.execute(
                """
                INSERT INTO appointments (patient_id, slot_id) VALUES (%s, %s)
                RETURNING id, patient_id, slot_id, status, created_at, approved_at
                """,
                (user.id, body.slot_id),
            ).fetchone()
            if assessment is not None:
                _store_triage(
                    conn,
                    row["id"],
                    assessment,
                    latency_ms,
                    user.id,
                    suggested_tests(body.symptoms),
                )
            if body.assessment_id is not None:
                conn.execute(
                    "UPDATE triage_results SET appointment_id = %s WHERE id = %s",
                    (row["id"], body.assessment_id),
                )
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

    assessment, latency_ms = _assess(triage, body.symptoms)
    try:
        with conn.transaction():
            row = _store_triage(
                conn,
                body.appointment_id,
                assessment,
                latency_ms,
                user.id,
                suggested_tests(body.symptoms),
            )
    except errors.UniqueViolation as exc:
        # Two intakes for the same appointment raced each other
        raise HTTPException(status.HTTP_409_CONFLICT, "Intake already submitted") from exc
    return TriageRecord.model_validate(row)


def _assess(triage: TriageServiceClient, symptoms: str) -> tuple[TriageAssessment, int]:
    assessment, latency_ms = triage.assess(symptoms)
    metrics.TRIAGE_CALL_SECONDS.observe(latency_ms / 1000)
    if assessment.fallback:
        metrics.TRIAGE_FALLBACKS.inc()
    return assessment, latency_ms


def _store_triage(
    conn: psycopg.Connection,
    appointment_id: int | None,
    assessment: TriageAssessment,
    latency_ms: int,
    patient_id: int,
    tests: list[str],
) -> dict:
    """Store only the structured result and the suggested tests. The symptom text is never
    written to the database."""
    row = conn.execute(
        f"""
        INSERT INTO triage_results AS t
            (appointment_id, patient_id, ai_urgency, suggested_specialty, red_flags, summary,
             latency_ms, tokens_used, suggested_tests)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING {TRIAGE_COLUMNS}
        """,
        (
            appointment_id,
            patient_id,
            assessment.urgency,
            assessment.suggested_specialty,
            assessment.red_flags,
            assessment.summary,
            latency_ms,
            assessment.tokens_used,
            tests,
        ),
    ).fetchone()
    metrics.INTAKES.labels(assessment.urgency.value).inc()
    return row


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
