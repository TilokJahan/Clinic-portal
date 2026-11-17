"""Earlier-visit offers: a clinician offers an urgent patient an earlier slot; the patient decides.

Nothing is ever moved without the patient's yes. Accepting is one transaction: book the new slot,
move the intake and lab reports to it, cancel the old booking. The unique index on active slots
decides a race, so two patients can never end up in the same slot.
"""

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import errors

from app import db, metrics, urgency
from app.auth import Clinician, Patient
from app.metrics import STREAM_CLIENTS
from app.models import (
    MyAppointment,
    OfferResult,
    OffersDecline,
    PendingOffer,
    RescheduleOffer,
    RescheduleOfferCreate,
    Slot,
)
from app.urgency import EFFECTIVE_URGENCY, OPEN_TO_ALL

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
           a.approved_at IS NOT NULL AS approved, a.declined_at IS NOT NULL AS declined,
           a.decline_reason, po.offers
    FROM appointments a
    JOIN slots s ON s.id = a.slot_id
    JOIN providers p ON p.id = s.provider_id
    LEFT JOIN triage_results t ON t.appointment_id = a.id
    LEFT JOIN LATERAL (
        SELECT jsonb_agg(jsonb_build_object(
                   'id', o.id, 'slot_id', ns.id, 'starts_at', ns.starts_at,
                   'provider_name', np.name) ORDER BY ns.starts_at, o.id) AS offers
        FROM reschedule_offers o
        JOIN slots ns ON ns.id = o.proposed_slot_id
        JOIN providers np ON np.id = ns.provider_id
        WHERE o.appointment_id = a.id AND {_LIVE}
    ) po ON true
    WHERE a.patient_id = %(patient)s
      -- Cancelled bookings are left out, except a declined request whose time hasn't come yet:
      -- the patient needs to see it was declined, and why
      AND (a.status <> 'cancelled' OR (a.declined_at IS NOT NULL AND s.starts_at > now()))
      AND (%(only)s::bigint IS NULL OR a.id = %(only)s)
    ORDER BY s.starts_at
"""


def load_my_appointments(
    conn: psycopg.Connection, patient_id: int, only: int | None = None
) -> list[MyAppointment]:
    """A patient's bookings, soonest first, with any open offer. Cancelled ones are left out,
    except a declined request whose time hasn't come yet."""
    rows = conn.execute(_MY_APPOINTMENTS_SQL, {"patient": patient_id, "only": only}).fetchall()
    return _to_my_appointments(rows)


async def my_appointment_events(
    connect: Callable[[], Awaitable[psycopg.AsyncConnection]],
    is_disconnected: Callable[[], Awaitable[bool]],
    patient_id: int,
    heartbeat_seconds: float = 15.0,
) -> AsyncIterator[str]:
    """Server-Sent Events for one patient: their appointments on connect, then again whenever
    they change, e.g. when a clinician offers an earlier visit.

    Listens on the same "queue_changed" NOTIFY channel as the clinician queue (it fires on any
    change to appointments, triage, lab reports or offers) and sends only when this patient's
    own list actually differs, so other patients' changes never reach them.
    """
    STREAM_CLIENTS.inc()
    try:
        async with await connect() as conn:
            await conn.execute("LISTEN queue_changed")

            async def snapshot() -> str:
                cur = await conn.execute(
                    _MY_APPOINTMENTS_SQL, {"patient": patient_id, "only": None}
                )
                items = _to_my_appointments(await cur.fetchall())
                return json.dumps([a.model_dump(mode="json") for a in items])

            last = await snapshot()
            yield f"event: appointments\ndata: {last}\n\n"
            while not await is_disconnected():
                changed = False
                async for _ in conn.notifies(timeout=heartbeat_seconds, stop_after=1):
                    changed = True
                current = await snapshot() if changed else last
                if current != last:
                    last = current
                    yield f"event: appointments\ndata: {current}\n\n"
                else:
                    yield ": keep-alive\n\n"
    finally:
        STREAM_CLIENTS.dec()


def _to_my_appointments(rows: list[dict]) -> list[MyAppointment]:
    result = []
    for row in rows:
        offers = [PendingOffer(**o) for o in row["offers"] or []]
        fields = {k: v for k, v in row.items() if k != "offers"}
        result.append(
            MyAppointment(
                **fields, pending_offers=offers, pending_offer=offers[0] if offers else None
            )
        )
    return result


def _booked_appointment(conn: psycopg.Connection, appointment_id: int, lock: bool = False) -> dict:
    row = conn.execute(
        """
        SELECT a.id, a.status, s.provider_id, s.starts_at
        FROM appointments a JOIN slots s ON s.id = a.slot_id WHERE a.id = %s
        """
        + (" FOR UPDATE OF a" if lock else ""),
        (appointment_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
    if row["status"] != "booked":
        raise HTTPException(status.HTTP_409_CONFLICT, "Appointment is not booked")
    return row


@router.get("/appointments/{appointment_id}/earlier-slots")
def earlier_slots(conn: Conn, _: Clinician, appointment_id: int) -> list[Slot]:
    """Free, upcoming slots with any provider that start before this visit (at most 10),
    soonest first; at the same time, the patient's own provider comes first.

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
        WHERE a.id IS NULL AND s.starts_at > now() AND s.starts_at < %(before)s
        ORDER BY s.starts_at, s.provider_id <> %(provider)s, s.provider_id
        LIMIT 10
        """,
        {"provider": current["provider_id"], "before": current["starts_at"]},
    ).fetchall()
    return [Slot(**row) for row in rows]


_LIMIT_SQL = f"""
    SELECT {EFFECTIVE_URGENCY} AS effective
    FROM appointments a
    LEFT JOIN triage_results t ON t.appointment_id = a.id
    LEFT JOIN LATERAL (
        SELECT * FROM lab_reports lr WHERE lr.appointment_id = a.id
        ORDER BY lr.uploaded_at DESC LIMIT 1
    ) l ON true
    WHERE a.id = %s
"""


def _limit_hours(conn: psycopg.Connection, appointment_id: int) -> int:
    """How soon this patient should be seen, from the same urgency the queue shows."""
    row = conn.execute(_LIMIT_SQL, (appointment_id,)).fetchone()
    return urgency.max_within_hours(row["effective"] if row else None)


# Times a clinician may propose: free and upcoming, with any provider, and either inside the
# patient's limit or at least earlier than their current visit (when nothing is free in time,
# sooner is still safer). Includes the urgent reserve: offering it is what it is for.
_PROPOSABLE = """
    s.starts_at > now()
    AND (s.starts_at <= now() + %(limit)s OR s.starts_at < %(current)s)
    AND NOT EXISTS (
        SELECT 1 FROM appointments x WHERE x.slot_id = s.id AND x.status <> 'cancelled'
    )
"""


@router.get("/appointments/{appointment_id}/alternative-slots")
def alternative_slots(conn: Conn, _: Clinician, appointment_id: int) -> list[Slot]:
    """Times the clinician can propose instead of the requested one (at most 12), soonest first;
    at the same time, the patient's own provider comes first."""
    current = _booked_appointment(conn, appointment_id)
    rows = conn.execute(
        f"""
        SELECT s.id, s.provider_id, p.name AS provider_name, p.specialty, s.starts_at, s.ends_at,
               NOT {OPEN_TO_ALL} AS reserved
        FROM slots s JOIN providers p ON p.id = s.provider_id
        WHERE {_PROPOSABLE}
        ORDER BY s.starts_at, s.provider_id <> %(provider)s, s.provider_id
        LIMIT 12
        """,
        {
            "limit": timedelta(hours=_limit_hours(conn, appointment_id)),
            "current": current["starts_at"],
            "provider": current["provider_id"],
        },
    ).fetchall()
    return [Slot(**row) for row in rows]


def propose_times(
    conn: psycopg.Connection, clinician_id: int, appointment_id: int, body: RescheduleOfferCreate
) -> list[RescheduleOffer]:
    """Propose one to three times. They replace any times proposed before; nothing moves until
    the patient accepts one."""
    slot_ids = body.slot_ids or ([body.slot_id] if body.slot_id else [])
    if not slot_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose at least one time")
    if len(set(slot_ids)) != len(slot_ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Each time can be proposed once")
    with conn.transaction():
        current = _booked_appointment(conn, appointment_id, lock=True)
        params = {
            "limit": timedelta(hours=_limit_hours(conn, appointment_id)),
            "current": current["starts_at"],
        }
        slots = {}
        for slot_id in slot_ids:
            slot = conn.execute(
                f"""
                SELECT s.id, s.starts_at, s.starts_at > now() AS upcoming, p.name AS provider_name,
                       EXISTS (SELECT 1 FROM appointments x
                               WHERE x.slot_id = s.id AND x.status <> 'cancelled') AS taken,
                       {_PROPOSABLE} AS proposable
                FROM slots s JOIN providers p ON p.id = s.provider_id WHERE s.id = %(id)s
                """,
                {**params, "id": slot_id},
            ).fetchone()
            if slot is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Slot not found")
            if not slot["upcoming"]:
                raise HTTPException(status.HTTP_409_CONFLICT, "Slot has already started")
            if slot["taken"]:
                raise HTTPException(status.HTTP_409_CONFLICT, "Slot is already booked")
            if not slot["proposable"]:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "That time is later than the patient's priority allows",
                )
            slots[slot_id] = slot
        # New proposals replace the old ones
        conn.execute(
            "UPDATE reschedule_offers SET status = 'expired', responded_at = now() "
            "WHERE appointment_id = %s AND status = 'pending'",
            (appointment_id,),
        )
        offers = []
        for slot_id in slot_ids:
            row = conn.execute(
                """
                INSERT INTO reschedule_offers (appointment_id, proposed_slot_id, offered_by, reason)
                VALUES (%s, %s, %s, %s)
                RETURNING id, appointment_id, proposed_slot_id, status, reason, created_at
                """,
                (appointment_id, slot_id, clinician_id, body.reason),
            ).fetchone()
            slot = slots[slot_id]
            offers.append(
                RescheduleOffer(
                    **row, provider_name=slot["provider_name"], starts_at=slot["starts_at"]
                )
            )
    metrics.RESCHEDULE_OFFERS.labels("offered").inc(len(offers))
    return offers


@router.post("/appointments/{appointment_id}/proposals", status_code=status.HTTP_201_CREATED)
def propose(
    conn: Conn, user: Clinician, appointment_id: int, body: RescheduleOfferCreate
) -> list[RescheduleOffer]:
    """Propose up to three times; the patient accepts one, picks their own, or declines them."""
    return propose_times(conn, user.id, appointment_id, body)


@router.post(
    "/appointments/{appointment_id}/reschedule-offers", status_code=status.HTTP_201_CREATED
)
def offer_earlier_visit(
    conn: Conn, user: Clinician, appointment_id: int, body: RescheduleOfferCreate
) -> RescheduleOffer:
    """Propose a single time (the first form of POST /appointments/{id}/proposals)."""
    return propose_times(conn, user.id, appointment_id, body)[0]


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
            SELECT o.status, o.appointment_id, o.proposed_slot_id, o.offered_by, a.patient_id,
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
        # The clinician chose this time, so it needs no further approval
        conn.execute(
            "UPDATE appointments SET approved_at = now(), approved_by = %s WHERE id = %s",
            (offer["offered_by"], new_id),
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
def decline_offer(
    conn: Conn, user: Patient, offer_id: int, body: OffersDecline | None = None
) -> OfferResult:
    """None of the proposed times work: all of them are declined, with an optional note for the
    clinician. The booking stays as it is; the patient can also choose another time themselves."""
    note = (body.note or "").strip() if body else ""
    offer = conn.execute(
        "SELECT o.appointment_id, o.status FROM reschedule_offers o "
        "JOIN appointments a ON a.id = o.appointment_id WHERE o.id = %s AND a.patient_id = %s",
        (offer_id, user.id),
    ).fetchone()
    if offer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Offer not found")
    if offer["status"] != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "This offer is no longer available")
    rows = conn.execute(
        """
        UPDATE reschedule_offers SET status = 'declined', responded_at = now(),
               patient_note = nullif(%s, '')
        WHERE appointment_id = %s AND status = 'pending'
        RETURNING id
        """,
        (note, offer["appointment_id"]),
    ).fetchall()
    metrics.RESCHEDULE_OFFERS.labels("declined").inc(len(rows))
    return OfferResult(id=offer_id, status="declined")
