"""Choosing when to be seen: the urgency matrix, timeframe search and patient rescheduling.

The patient picks a timeframe ("within 3 days"), sees the free times in it and accepts one. The
urgency matrix (app/urgency.py) caps the timeframe: an urgent patient can only choose a visit in
the next 24 hours, never a later one. Moving uses the same transaction as accepting a clinician's
offer (app/reschedule.py), so the intake and lab reports follow the patient and the unique index
on active slots still prevents double booking.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg import errors

from app import db, metrics, urgency
from app.auth import AnyUser, Patient
from app.models import MyAppointment, RescheduleRequest, ScheduleOptions, Slot, UrgencyMatrix
from app.queue import EFFECTIVE_URGENCY
from app.reschedule import load_my_appointments, move_booking

router = APIRouter()
Conn = Annotated[psycopg.Connection, Depends(db.get_conn)]
WithinHours = Annotated[
    int | None, Query(description="One of the timeframes in GET /urgency-matrix, in hours")
]

# Free, upcoming slots that start before a cutoff, earliest first
_FREE_SLOTS_SQL = """
    SELECT s.id, s.provider_id, p.name AS provider_name, p.specialty, s.starts_at, s.ends_at
    FROM slots s
    JOIN providers p ON p.id = s.provider_id
    LEFT JOIN appointments a ON a.slot_id = s.id AND a.status <> 'cancelled'
    WHERE a.id IS NULL AND s.starts_at > now() AND s.starts_at <= now() + %(within)s
      AND (%(provider_id)s::bigint IS NULL OR s.provider_id = %(provider_id)s)
    ORDER BY s.starts_at, s.provider_id
    LIMIT %(limit)s
"""

# One of the patient's own appointments with its priorities. The same EFFECTIVE_URGENCY as the
# queue, so the patient's limit always matches where the clinician sees them.
_APPOINTMENT_SQL = f"""
    SELECT a.id, a.status, s.starts_at, s.provider_id,
           coalesce(t.final_urgency, t.ai_urgency) AS priority,
           {EFFECTIVE_URGENCY} AS effective
    FROM appointments a
    JOIN slots s ON s.id = a.slot_id
    LEFT JOIN triage_results t ON t.appointment_id = a.id
    LEFT JOIN LATERAL (
        SELECT * FROM lab_reports lr WHERE lr.appointment_id = a.id
        ORDER BY lr.uploaded_at DESC LIMIT 1
    ) l ON true
    WHERE a.id = %(id)s AND a.patient_id = %(patient)s
"""


def _check_timeframe(within_hours: int) -> None:
    if within_hours not in urgency.TIMEFRAME_HOURS:
        allowed = ", ".join(str(h) for h in sorted(urgency.TIMEFRAME_HOURS))
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"within_hours must be one of {allowed}"
        )


def _free_slots(
    conn: psycopg.Connection, within_hours: int, provider_id: int | None = None, limit: int = 12
) -> list[Slot]:
    rows = conn.execute(
        _FREE_SLOTS_SQL,
        {"within": timedelta(hours=within_hours), "provider_id": provider_id, "limit": limit},
    ).fetchall()
    return [Slot(**row) for row in rows]


def _own_appointment(
    conn: psycopg.Connection, patient_id: int, appointment_id: int, lock: bool = False
) -> dict:
    row = conn.execute(
        _APPOINTMENT_SQL + (" FOR UPDATE OF a" if lock else ""),
        {"id": appointment_id, "patient": patient_id},
    ).fetchone()
    if row is None:  # also when it belongs to someone else: don't reveal it exists
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
    if row["status"] != "booked":
        raise HTTPException(status.HTTP_409_CONFLICT, "Appointment is not booked")
    return row


def _limit_message(hours: int) -> str:
    label = next(t.label for t in urgency.TIMEFRAMES if t.hours == hours)
    return f"Your care team needs to see you {label.lower()}. Please choose an earlier time."


@router.get("/urgency-matrix")
def urgency_matrix(_: AnyUser) -> UrgencyMatrix:
    """How a priority is decided and how soon each priority should be seen."""
    return urgency.matrix()


@router.get("/slots/earliest")
def earliest_slots(
    conn: Conn,
    _: AnyUser,
    within_hours: Annotated[int, Query(description="One of the timeframes, in hours")],
    provider_id: Annotated[int | None, Query(gt=0)] = None,
) -> list[Slot]:
    """Free times in the next within_hours, earliest first (at most 12), to book by timeframe."""
    _check_timeframe(within_hours)
    return _free_slots(conn, within_hours, provider_id)


@router.get("/appointments/{appointment_id}/schedule-options")
def schedule_options(
    conn: Conn, user: Patient, appointment_id: int, within_hours: WithinHours = None
) -> ScheduleOptions:
    """Free times the patient can move this visit to, in the timeframe they chose.

    Without within_hours, uses the longest timeframe their priority allows. Asking for a longer
    one than allowed is a 422 that says how soon they need to be seen.
    """
    row = _own_appointment(conn, user.id, appointment_id)
    limit = urgency.max_within_hours(row["effective"])
    within = limit if within_hours is None else within_hours
    _check_timeframe(within)
    if within > limit:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, _limit_message(limit))
    return ScheduleOptions(
        appointment_id=appointment_id,
        starts_at=row["starts_at"],
        priority=row["priority"],
        max_within_hours=limit,
        care_team_limit=limit < urgency.max_within_hours(row["priority"]),
        within_hours=within,
        current_fits=row["starts_at"] <= datetime.now(UTC) + timedelta(hours=within),
        slots=_free_slots(conn, within),
    )


@router.post("/appointments/{appointment_id}/reschedule")
def reschedule(
    conn: Conn, user: Patient, appointment_id: int, body: RescheduleRequest
) -> MyAppointment:
    """The patient accepts a new time for this visit. Their intake and lab reports move with it.

    The new time must start within the longest timeframe their priority allows.
    """
    with conn.transaction():
        row = _own_appointment(conn, user.id, appointment_id, lock=True)
        limit = urgency.max_within_hours(row["effective"])
        slot = conn.execute(
            """
            SELECT starts_at > now() AS upcoming, starts_at <= now() + %s AS within_limit
            FROM slots WHERE id = %s
            """,
            (timedelta(hours=limit), body.slot_id),
        ).fetchone()
        if slot is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Slot not found")
        if not slot["upcoming"]:
            raise HTTPException(status.HTTP_409_CONFLICT, "Slot has already started")
        if not slot["within_limit"]:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, _limit_message(limit))
        try:
            new_id = move_booking(conn, user.id, appointment_id, body.slot_id)
        except errors.UniqueViolation as exc:
            # Also when it is the slot they already have
            metrics.BOOKING_CONFLICTS.labels("already_booked").inc()
            raise HTTPException(status.HTTP_409_CONFLICT, "Slot is already booked") from exc
    metrics.PATIENT_RESCHEDULES.inc()
    return load_my_appointments(conn, user.id, only=new_id)[0]
