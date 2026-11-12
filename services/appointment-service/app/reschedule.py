"""Earlier-visit offers: a clinician offers an urgent patient an earlier slot; the patient decides.

Nothing is ever moved without the patient's yes. Accepting is one transaction: book the new slot,
move the intake and lab reports to it, cancel the old booking. The unique index on active slots
decides a race, so two patients can never end up in the same slot.
"""

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import errors

from app import db, metrics
from app.auth import Clinician, Patient
from app.models import (
    MyAppointment,
    OfferResult,
    PendingOffer,
    RescheduleOffer,
    RescheduleOfferCreate,
    Slot,
)
from app.urgency import OPEN_TO_ALL

router = APIRouter()
Conn = Annotated[psycopg.Connection, Depends(db.get_conn)]

# An offer a patient can still act on: pending, its slot not started and still free. An offer
# whose slot was taken meanwhile is stale, and is treated as if it wasn't there.
_LIVE = """
    o.status = 'pending' AND ns.starts_at > now()
    AND NOT EXISTS (
        SELECT 1 FROM appointments x
        WHERE x.slot_id = o.proposed_slot_id AND x.status <> 'cancelled'
    )
"""
# For queries on appointments a: is there a live offer?
OFFER_PENDING = f"""EXISTS (
    SELECT 1 FROM reschedule_offers o JOIN slots ns ON ns.id = o.proposed_slot_id
    WHERE o.appointment_id = a.id AND {_LIVE}
)"""

_MY_APPOINTMENTS_SQL = f"""
    SELECT a.id, a.slot_id, a.status, a.created_at, s.starts_at,
           p.name AS provider_name, p.specialty, t.id IS NOT NULL AS intake_submitted,
           po.id AS offer_id, po.slot_id AS offer_slot_id, po.starts_at AS offer_starts_at,
           po.provider_name AS offer_provider_name
    FROM appointments a
    JOIN slots s ON s.id = a.slot_id
    JOIN providers p ON p.id = s.provider_id
    LEFT JOIN triage_results t ON t.appointment_id = a.id
    LEFT JOIN LATERAL (
        SELECT o.id, ns.id AS slot_id, ns.starts_at, np.name AS provider_name
        FROM reschedule_offers o
        JOIN slots ns ON ns.id = o.proposed_slot_id
        JOIN providers np ON np.id = ns.provider_id
        WHERE o.appointment_id = a.id AND {_LIVE}
    ) po ON true
    WHERE a.patient_id = %(patient)s AND a.status <> 'cancelled'
      AND (%(only)s::bigint IS NULL OR a.id = %(only)s)
    ORDER BY s.starts_at
"""


def load_my_appointments(
    conn: psycopg.Connection, patient_id: int, only: int | None = None
) -> list[MyAppointment]:
    """A patient's bookings that aren't cancelled, soonest first, with any open offer."""
    rows = conn.execute(_MY_APPOINTMENTS_SQL, {"patient": patient_id, "only": only}).fetchall()
    result = []
    for row in rows:
        offer = None
        if row["offer_id"] is not None:
            offer = PendingOffer(
                id=row["offer_id"],
                slot_id=row["offer_slot_id"],
                starts_at=row["offer_starts_at"],
                provider_name=row["offer_provider_name"],
            )
        fields = {k: v for k, v in row.items() if not k.startswith("offer_")}
        result.append(MyAppointment(**fields, pending_offer=offer))
    return result


def _booked_appointment(conn: psycopg.Connection, appointment_id: int) -> dict:
    row = conn.execute(
        """
        SELECT a.id, a.status, s.provider_id, s.starts_at
        FROM appointments a JOIN slots s ON s.id = a.slot_id WHERE a.id = %s
        """,
        (appointment_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
    if row["status"] != "booked":
        raise HTTPException(status.HTTP_409_CONFLICT, "Appointment is not booked")
    return row


@router.get("/appointments/{appointment_id}/earlier-slots")
def earlier_slots(conn: Conn, _: Clinician, appointment_id: int) -> list[Slot]:
    """Free, upcoming slots with the same provider that start before this visit (at most 10).

    Includes the urgent reserve: offering it to an urgent patient is what it is for.
    """
    current = _booked_appointment(conn, appointment_id)
    rows = conn.execute(
        f"""
        SELECT s.id, s.provider_id, p.name AS provider_name, p.specialty, s.starts_at, s.ends_at,
               NOT {OPEN_TO_ALL} AS reserved
        FROM slots s
        JOIN providers p ON p.id = s.provider_id
        LEFT JOIN appointments a ON a.slot_id = s.id AND a.status <> 'cancelled'
        WHERE a.id IS NULL AND s.provider_id = %(provider)s
          AND s.starts_at > now() AND s.starts_at < %(before)s
        ORDER BY s.starts_at
        LIMIT 10
        """,
        {"provider": current["provider_id"], "before": current["starts_at"]},
    ).fetchall()
    return [Slot(**row) for row in rows]


@router.post(
    "/appointments/{appointment_id}/reschedule-offers", status_code=status.HTTP_201_CREATED
)
def offer_earlier_visit(
    conn: Conn, user: Clinician, appointment_id: int, body: RescheduleOfferCreate
) -> RescheduleOffer:
    """Offer the patient an earlier slot. The patient accepts or declines; nothing moves yet."""
    current = _booked_appointment(conn, appointment_id)
    slot = conn.execute(
        """
        SELECT s.starts_at, s.starts_at > now() AS upcoming, p.name AS provider_name
        FROM slots s JOIN providers p ON p.id = s.provider_id WHERE s.id = %s
        """,
        (body.slot_id,),
    ).fetchone()
    if slot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Slot not found")
    if not slot["upcoming"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "Slot has already started")
    if slot["starts_at"] >= current["starts_at"]:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "The slot must be earlier than the current visit"
        )
    taken = conn.execute(
        "SELECT 1 FROM appointments WHERE slot_id = %s AND status <> 'cancelled'", (body.slot_id,)
    ).fetchone()
    if taken:
        raise HTTPException(status.HTTP_409_CONFLICT, "Slot is already booked")
    try:
        with conn.transaction():
            # An old offer whose slot has since been taken doesn't block a new one
            conn.execute(
                """
                UPDATE reschedule_offers o SET status = 'expired', responded_at = now()
                FROM slots ns
                WHERE o.appointment_id = %s AND o.status = 'pending' AND ns.id = o.proposed_slot_id
                  AND NOT ("""
                + _LIVE
                + """)
                """,
                (appointment_id,),
            )
            row = conn.execute(
                """
                INSERT INTO reschedule_offers (appointment_id, proposed_slot_id, offered_by, reason)
                VALUES (%s, %s, %s, %s)
                RETURNING id, appointment_id, proposed_slot_id, status, reason, created_at
                """,
                (appointment_id, body.slot_id, user.id, body.reason),
            ).fetchone()
    except errors.UniqueViolation as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "An offer is already pending") from exc
    metrics.RESCHEDULE_OFFERS.labels("offered").inc()
    return RescheduleOffer(**row, provider_name=slot["provider_name"], starts_at=slot["starts_at"])


def move_booking(conn: psycopg.Connection, patient_id: int, old_id: int, slot_id: int) -> int:
    """Book slot_id for the patient, move the intake and lab reports over, cancel old_id.

    Call it inside a transaction that has locked the old appointment. Returns the new
    appointment's id. Raises UniqueViolation if the slot is taken; the insert runs in a savepoint,
    so the caller's transaction is still usable afterwards.
    """
    with conn.transaction():
        new_id = conn.execute(
            "INSERT INTO appointments (patient_id, slot_id) VALUES (%s, %s) RETURNING id",
            (patient_id, slot_id),
        ).fetchone()["id"]
    # The intake and lab reports follow the patient, or they'd stay on the cancelled booking
    # and drop out of the queue, which only lists booked and checked-in visits
    conn.execute(
        "UPDATE triage_results SET appointment_id = %s WHERE appointment_id = %s", (new_id, old_id)
    )
    conn.execute(
        "UPDATE lab_reports SET appointment_id = %s WHERE appointment_id = %s", (new_id, old_id)
    )
    # Offers for the old visit can't be used any more (the caller may then mark one accepted)
    conn.execute(
        "UPDATE reschedule_offers SET status = 'expired', responded_at = now() "
        "WHERE appointment_id = %s AND status = 'pending'",
        (old_id,),
    )
    conn.execute("UPDATE appointments SET status = 'cancelled' WHERE id = %s", (old_id,))
    return new_id


def _accept(conn: psycopg.Connection, patient_id: int, offer_id: int) -> int | str:
    """Move the patient to the offered slot. Returns the new appointment's id, or the reason the
    offer can't be accepted (the caller answers 409; the offer is marked expired if it lapsed)."""
    with conn.transaction():
        offer = conn.execute(
            """
            SELECT o.status, o.appointment_id, o.proposed_slot_id, a.patient_id,
                   a.status AS appointment_status, s.starts_at > now() AS upcoming
            FROM reschedule_offers o
            JOIN appointments a ON a.id = o.appointment_id
            JOIN slots s ON s.id = o.proposed_slot_id
            WHERE o.id = %s
            FOR UPDATE OF o, a
            """,
            (offer_id,),
        ).fetchone()
        # Someone else's offer looks the same as one that doesn't exist
        if offer is None or offer["patient_id"] != patient_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Offer not found")
        if offer["status"] != "pending":
            return "This offer is no longer available"

        lapsed = None
        new_id = None
        if offer["appointment_status"] != "booked":
            lapsed = "Your appointment has changed"
        elif not offer["upcoming"]:
            lapsed = "That time has already started"
        else:
            try:
                new_id = move_booking(
                    conn, patient_id, offer["appointment_id"], offer["proposed_slot_id"]
                )
            except errors.UniqueViolation:  # someone else got the slot first
                lapsed = "That time was just taken"
        if lapsed:
            conn.execute(
                "UPDATE reschedule_offers SET status = 'expired', responded_at = now() "
                "WHERE id = %s",
                (offer_id,),
            )
            return lapsed

        conn.execute(
            "UPDATE reschedule_offers SET status = 'accepted', responded_at = now() WHERE id = %s",
            (offer_id,),
        )
        return new_id


@router.post("/reschedule-offers/{offer_id}/accept")
def accept_offer(conn: Conn, user: Patient, offer_id: int) -> MyAppointment:
    """Accept: you move to the earlier slot, with your intake and lab reports. 409 if it's gone."""
    result = _accept(conn, user.id, offer_id)
    conn.commit()  # keep an "expired" mark even though the answer is a 409
    if isinstance(result, str):
        if result != "This offer is no longer available":
            metrics.RESCHEDULE_OFFERS.labels("expired").inc()
        raise HTTPException(status.HTTP_409_CONFLICT, result)
    metrics.RESCHEDULE_OFFERS.labels("accepted").inc()
    return load_my_appointments(conn, user.id, only=result)[0]


@router.post("/reschedule-offers/{offer_id}/decline")
def decline_offer(conn: Conn, user: Patient, offer_id: int) -> OfferResult:
    """Decline: your booking stays as it is."""
    row = conn.execute(
        """
        UPDATE reschedule_offers o SET status = 'declined', responded_at = now()
        FROM appointments a
        WHERE o.id = %s AND a.id = o.appointment_id AND a.patient_id = %s
          AND o.status = 'pending'
        RETURNING o.id, o.status
        """,
        (offer_id, user.id),
    ).fetchone()
    if row is None:
        mine = conn.execute(
            "SELECT 1 FROM reschedule_offers o JOIN appointments a ON a.id = o.appointment_id "
            "WHERE o.id = %s AND a.patient_id = %s",
            (offer_id, user.id),
        ).fetchone()
        if mine is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Offer not found")
        raise HTTPException(status.HTTP_409_CONFLICT, "This offer is no longer available")
    metrics.RESCHEDULE_OFFERS.labels("declined").inc()
    return OfferResult(**row)
