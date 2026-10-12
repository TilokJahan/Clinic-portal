from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, status
from psycopg import errors

from app import db
from app.models import Appointment, AppointmentCreate, Slot


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    db.open_pool()
    yield
    db.close_pool()


app = FastAPI(title="Appointment Service", version="0.1.0", lifespan=lifespan)

Conn = Annotated[psycopg.Connection, Depends(db.get_conn)]


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
    """Unbooked slots that start on the given day, earliest first."""
    start = datetime.combine(day, time.min, tzinfo=UTC)
    rows = conn.execute(
        """
        SELECT s.id, s.provider_id, s.starts_at, s.ends_at
        FROM slots s
        LEFT JOIN appointments a ON a.slot_id = s.id
        WHERE a.id IS NULL
          AND s.starts_at >= %(start)s AND s.starts_at < %(end)s
          AND (%(provider_id)s::bigint IS NULL OR s.provider_id = %(provider_id)s)
        ORDER BY s.starts_at, s.provider_id
        """,
        {"start": start, "end": start + timedelta(days=1), "provider_id": provider_id},
    ).fetchall()
    return [Slot(**row) for row in rows]


@app.post("/appointments", status_code=status.HTTP_201_CREATED)
def book_appointment(conn: Conn, body: AppointmentCreate) -> Appointment:
    """Book a slot. Returns 409 if someone already booked it."""
    try:
        with conn.transaction():
            slot = conn.execute("SELECT 1 FROM slots WHERE id = %s", (body.slot_id,)).fetchone()
            if slot is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Slot not found")
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
        # The UNIQUE (slot_id) constraint catches double booking, including concurrent requests.
        raise HTTPException(status.HTTP_409_CONFLICT, "Slot is already booked") from exc
    return Appointment(**row)


# TODO (Backend A): intake, queue, SSE stream. See docs/api.md for the contract.
