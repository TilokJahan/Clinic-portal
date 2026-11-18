"""Lab visits: when the patient comes to the lab for a requested test.

After a clinician or physician requests a test (app/labs.py), the lab technician proposes up to
three times, as soon as the urgency needs: urgent within 24 hours, soon within 3 days, routine
within 2 weeks. The patient accepts one, or chooses any other free lab time in that window (or,
when nothing at all is free in it, the first free times after). The lab sees one patient at a
time; a unique index makes sure two patients never get the same time.
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import errors
from pydantic import BaseModel, Field

from app import db, metrics
from app.auth import LabTech, Patient
from app.models import LabRequestSummary
from app.urgency import CLINIC_TIME_ZONE, SEEN_WITHIN_HOURS

router = APIRouter()
Conn = Annotated[psycopg.Connection, Depends(db.get_conn)]

ZONE = ZoneInfo(CLINIC_TIME_ZONE)
# Lab opening hours (clinic time), weekdays, one patient every 15 minutes
OPENS, CLOSES = time(8, 0), time(16, 0)
STEP = timedelta(minutes=15)
HORIZON_DAYS = 21
OPEN = ("requested", "proposed", "scheduled")
SUMMARY = "id, exam_type, urgency, status, requested_at, note, proposed_times, scheduled_at"


class LabTimes(BaseModel):
    # How soon the urgency needs the test, and whether the times below fit in it
    within_hours: int
    in_time: bool
    times: list[datetime]


class LabProposal(BaseModel):
    times: list[datetime] = Field(min_length=1, max_length=3)


class LabChoice(BaseModel):
    starts_at: datetime


def _candidates(now: datetime, days: int = HORIZON_DAYS):
    """Every lab time from now on, in order (UTC)."""
    local_now = now.astimezone(ZONE)
    for offset in range(days + 1):
        day: date = local_now.date() + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        at = datetime.combine(day, OPENS, tzinfo=ZONE)
        end = datetime.combine(day, CLOSES, tzinfo=ZONE)
        while at < end:
            if at > now:
                yield at.astimezone(UTC)
            at += STEP


def _booked(conn: psycopg.Connection) -> set[datetime]:
    rows = conn.execute(
        "SELECT scheduled_at FROM lab_requests WHERE status = 'scheduled' AND scheduled_at > now()"
    ).fetchall()
    return {r["scheduled_at"] for r in rows}


def free_times(conn: psycopg.Connection, urgency: str, limit: int = 12) -> LabTimes:
    """Free lab times within the urgency's window, earliest first. If none is free in it, the
    first free times after (better late than never; the lab and clinician can see it's late)."""
    hours = SEEN_WITHIN_HOURS[urgency]
    now = datetime.now(UTC)
    deadline = now + timedelta(hours=hours)
    booked = _booked(conn)
    free = [t for t in _candidates(now) if t not in booked]
    in_window = [t for t in free if t <= deadline]
    if in_window:
        return LabTimes(within_hours=hours, in_time=True, times=in_window[:limit])
    return LabTimes(within_hours=hours, in_time=False, times=free[:limit])


def _is_lab_time(at: datetime) -> bool:
    local = at.astimezone(ZONE)
    on_step = local.minute % 15 == 0 and local.second == 0 and local.microsecond == 0
    return local.weekday() < 5 and OPENS <= local.time() < CLOSES and on_step


def _allowed(conn: psycopg.Connection, urgency: str, at: datetime) -> bool:
    """A time the patient may choose: a free lab time in the window, or after it only when
    nothing in the window is free."""
    if at <= datetime.now(UTC) or not _is_lab_time(at) or at in _booked(conn):
        return False
    options = free_times(conn, urgency, limit=1000)
    return at in options.times or (not options.in_time and at >= options.times[0])


def _request(conn: psycopg.Connection, request_id: int, patient_id: int | None = None) -> dict:
    row = conn.execute(
        f"""
        SELECT q.{SUMMARY.replace(", ", ", q.")}, a.patient_id
        FROM lab_requests q JOIN appointments a ON a.id = q.appointment_id
        WHERE q.id = %s FOR UPDATE OF q
        """,
        (request_id,),
    ).fetchone()
    # Another patient's request looks the same as one that doesn't exist
    if row is None or (patient_id is not None and row["patient_id"] != patient_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lab request not found")
    return row


# --- The lab technician proposes times ---------------------------------------------------------


@router.get("/lab/requests/{request_id}/times")
def lab_times(conn: Conn, _: LabTech, request_id: int) -> LabTimes:
    """Free lab times for this request's urgency, to propose to the patient."""
    row = _request(conn, request_id)
    return free_times(conn, row["urgency"])


@router.post("/lab/requests/{request_id}/propose")
def propose_lab_times(
    conn: Conn, _: LabTech, request_id: int, body: LabProposal
) -> LabRequestSummary:
    """Send the patient one to three lab times. They replace any proposed before."""
    times = sorted(set(body.times))
    with conn.transaction():
        row = _request(conn, request_id)
        if row["status"] not in ("requested", "proposed"):
            raise HTTPException(status.HTTP_409_CONFLICT, "This request is already scheduled")
        for at in times:
            if not _allowed(conn, row["urgency"], at):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "Choose free lab times that fit the urgency",
                )
        updated = conn.execute(
            f"""
            UPDATE lab_requests SET status = 'proposed', proposed_times = %s, updated_at = now()
            WHERE id = %s RETURNING {SUMMARY}
            """,
            (times, request_id),
        ).fetchone()
    metrics.LAB_VISITS.labels("proposed").inc()
    return LabRequestSummary(**updated)


# --- The patient accepts a time or chooses another ---------------------------------------------


@router.get("/lab-requests/{request_id}/times")
def my_lab_times(conn: Conn, user: Patient, request_id: int) -> LabTimes:
    """Free lab times you can choose for your test, in the time its urgency allows."""
    row = _request(conn, request_id, patient_id=user.id)
    if row["status"] not in ("requested", "proposed", "scheduled"):
        raise HTTPException(status.HTTP_409_CONFLICT, "This request is closed")
    return free_times(conn, row["urgency"], limit=40)


@router.post("/lab-requests/{request_id}/schedule")
def schedule_lab_visit(
    conn: Conn, user: Patient, request_id: int, body: LabChoice
) -> LabRequestSummary:
    """Book your lab visit: one of the times the lab proposed, or another free time that fits
    the urgency. You can move it again later the same way."""
    at = body.starts_at.astimezone(UTC)
    try:
        with conn.transaction():
            row = _request(conn, request_id, patient_id=user.id)
            if row["status"] not in OPEN:
                raise HTTPException(status.HTTP_409_CONFLICT, "This request is closed")
            proposed = at in row["proposed_times"]
            # Moving an existing booking: its own time doesn't count as taken
            if row["status"] == "scheduled":
                conn.execute(
                    "UPDATE lab_requests SET status = 'proposed', scheduled_at = NULL "
                    "WHERE id = %s",
                    (request_id,),
                )
            if not _allowed(conn, row["urgency"], at) and not (
                proposed and at > datetime.now(UTC) and at not in _booked(conn)
            ):
                raise HTTPException(
                    status.HTTP_409_CONFLICT, "That lab time isn't available. Please pick another."
                )
            updated = conn.execute(
                f"""
                UPDATE lab_requests SET status = 'scheduled', scheduled_at = %s, updated_at = now()
                WHERE id = %s RETURNING {SUMMARY}
                """,
                (at, request_id),
            ).fetchone()
    except errors.UniqueViolation as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That lab time was just taken. Please pick another."
        ) from exc
    metrics.LAB_VISITS.labels("proposed_time" if proposed else "own_time").inc()
    return LabRequestSummary(**{**updated, "note": None})
