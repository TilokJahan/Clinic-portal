"""The physician's (doctor's) side: their own schedule, and completing a visit with a summary.

A physician is linked to one provider (users.provider_id, set by an admin) and sees that
provider's visits: symptoms, triage, lab results and requests, like a clinician, but for their own
patients only. When they complete a visit they write a summary the patient reads afterwards.
"""

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app import db
from app.auth import CurrentUser, Physician
from app.models import Appointment, QueueEntry, VisitCompletion
from app.queue import ENTRY_SELECT, to_entry

router = APIRouter()
Conn = Annotated[psycopg.Connection, Depends(db.get_conn)]

# How long completed visits stay on the schedule page
RECENT_COMPLETED_DAYS = 14


def own_provider(conn: psycopg.Connection, user: CurrentUser) -> int | None:
    """The provider whose schedule this physician sees. None for an admin (all providers)."""
    if user.role == "admin":
        return None
    row = conn.execute("SELECT provider_id FROM users WHERE id = %s", (user.id,)).fetchone()
    if row is None or row["provider_id"] is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Your account isn't linked to a schedule yet. Ask an admin."
        )
    return row["provider_id"]


@router.get("/physician/schedule")
def schedule(
    conn: Conn,
    user: Physician,
    provider_id: Annotated[int | None, Query(gt=0, description="Admins: one provider")] = None,
) -> list[QueueEntry]:
    """Upcoming visits (and today's) with this physician, soonest first, then the visits they
    completed in the last two weeks."""
    mine = own_provider(conn, user)
    provider = mine if mine is not None else provider_id
    rows = conn.execute(
        f"""
        {ENTRY_SELECT}
        WHERE (%(provider)s::bigint IS NULL OR p.id = %(provider)s)
          AND ((a.status IN ('booked', 'checked_in')
                AND s.starts_at > date_trunc('day', now()))
               OR (a.status = 'completed'
                   AND a.completed_at > now() - interval '{RECENT_COMPLETED_DAYS} days'))
        ORDER BY a.status = 'completed', s.starts_at, a.id
        """,
        {"provider": provider},
    ).fetchall()
    return [to_entry(row) for row in rows]


@router.post("/appointments/{appointment_id}/complete")
def complete_visit(
    conn: Conn, user: Physician, appointment_id: int, body: VisitCompletion
) -> Appointment:
    """Complete one of your visits, with a summary the patient will read."""
    mine = own_provider(conn, user)
    with conn.transaction():
        row = conn.execute(
            """
            SELECT a.status, a.approved_at, s.provider_id
            FROM appointments a JOIN slots s ON s.id = a.slot_id
            WHERE a.id = %s FOR UPDATE OF a
            """,
            (appointment_id,),
        ).fetchone()
        # Another physician's visit looks the same as one that doesn't exist
        if row is None or (mine is not None and row["provider_id"] != mine):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
        if row["status"] not in ("booked", "checked_in"):
            raise HTTPException(status.HTTP_409_CONFLICT, "This visit is not open")
        if row["approved_at"] is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "The booking isn't approved yet")
        updated = conn.execute(
            """
            UPDATE appointments
            SET status = 'completed', visit_summary = %s, completed_at = now(), completed_by = %s
            WHERE id = %s
            RETURNING id, patient_id, slot_id, status, created_at, approved_at
            """,
            (body.summary.strip(), user.id, appointment_id),
        ).fetchone()
    return Appointment(**updated)
