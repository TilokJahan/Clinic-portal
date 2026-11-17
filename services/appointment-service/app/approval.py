"""Clinician approval of booking requests.

A patient requests a time and describes their symptoms; the slot is held while the request
waits. A clinician looks at the symptoms and urgency in the queue, then approves the request,
declines it (the slot opens again), or offers a different time (see app/reschedule.py; accepting
that offer counts as approved). A booked appointment with approved_at NULL is a request.
"""

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status

from app import db, metrics
from app.auth import Clinician
from app.models import Appointment, DeclineRequest

router = APIRouter()
Conn = Annotated[psycopg.Connection, Depends(db.get_conn)]

_RETURNING = "RETURNING id, patient_id, slot_id, status, created_at, approved_at"


def _waiting_request(conn: psycopg.Connection, appointment_id: int) -> dict:
    """Lock the appointment; 404 if unknown, 409 unless it is a request still waiting."""
    row = conn.execute(
        """
        SELECT a.status, a.approved_at, t.id AS triage_id
        FROM appointments a LEFT JOIN triage_results t ON t.appointment_id = a.id
        WHERE a.id = %s
        FOR UPDATE OF a
        """,
        (appointment_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
    if row["status"] != "booked":
        raise HTTPException(status.HTTP_409_CONFLICT, "This request is no longer open")
    if row["approved_at"] is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already approved")
    return row


@router.post("/appointments/{appointment_id}/approve")
def approve(conn: Conn, user: Clinician, appointment_id: int) -> Appointment:
    """Approve a request. Only once the patient has described their symptoms: the decision is
    based on them and on the urgency they lead to."""
    with conn.transaction():
        request = _waiting_request(conn, appointment_id)
        if request["triage_id"] is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "The patient hasn't described their symptoms yet"
            )
        row = conn.execute(
            "UPDATE appointments SET approved_at = now(), approved_by = %s WHERE id = %s "
            + _RETURNING,
            (user.id, appointment_id),
        ).fetchone()
    metrics.APPROVALS.labels("approved").inc()
    return Appointment(**row)


@router.post("/appointments/{appointment_id}/decline")
def decline(conn: Conn, user: Clinician, appointment_id: int, body: DeclineRequest) -> Appointment:
    """Decline a request. The slot opens again and the patient sees the reason, if given."""
    with conn.transaction():
        _waiting_request(conn, appointment_id)
        # An offered time for this request can't be used any more
        conn.execute(
            "UPDATE reschedule_offers SET status = 'expired', responded_at = now() "
            "WHERE appointment_id = %s AND status = 'pending'",
            (appointment_id,),
        )
        row = conn.execute(
            """
            UPDATE appointments
            SET status = 'cancelled', declined_at = now(), approved_by = %s,
                decline_reason = nullif(btrim(%s), '')
            WHERE id = %s
            """
            + _RETURNING,
            (user.id, body.reason or "", appointment_id),
        ).fetchone()
    metrics.APPROVALS.labels("declined").inc()
    return Appointment(**row)
