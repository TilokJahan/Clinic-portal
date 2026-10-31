"""Clinician queue: the query behind GET /queue and the event stream behind GET /queue/stream."""

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import psycopg

from app.models import QueueEntry, TriageRecord

TRIAGE_COLUMNS = """
    t.id, t.appointment_id, t.ai_urgency, t.final_urgency,
    coalesce(t.final_urgency, t.ai_urgency) AS urgency, t.overridden, t.suggested_specialty,
    t.red_flags, t.summary, t.latency_ms, t.tokens_used, t.created_at, t.reviewed_at
"""

# Waiting patients (booked or checked in). Most urgent first; within the same urgency, whoever
# submitted their intake first; patients without an intake yet go last, by appointment time.
QUEUE_SQL = """
    SELECT a.id AS appointment_id, a.patient_id, a.status, a.created_at AS booked_at,
           s.starts_at, p.id AS provider_id, p.name AS provider_name,
           to_jsonb(t) || jsonb_build_object('urgency', coalesce(t.final_urgency, t.ai_urgency))
               AS triage
    FROM appointments a
    JOIN slots s ON s.id = a.slot_id
    JOIN providers p ON p.id = s.provider_id
    LEFT JOIN triage_results t ON t.appointment_id = a.id
    WHERE a.status IN ('booked', 'checked_in')
    ORDER BY
        CASE coalesce(t.final_urgency, t.ai_urgency)
            WHEN 'urgent' THEN 0 WHEN 'soon' THEN 1 WHEN 'routine' THEN 2 ELSE 3
        END,
        t.created_at NULLS LAST, s.starts_at, a.id
"""


def patient_label(patient_id: int) -> str:
    return f"Patient {patient_id:04d}"


def to_entry(row: dict[str, Any]) -> QueueEntry:
    triage = row["triage"]
    return QueueEntry(
        appointment_id=row["appointment_id"],
        patient_label=patient_label(row["patient_id"]),
        provider_id=row["provider_id"],
        provider_name=row["provider_name"],
        starts_at=row["starts_at"],
        status=row["status"],
        booked_at=row["booked_at"],
        triage=TriageRecord.model_validate(triage) if triage and triage.get("id") else None,
    )


def load_queue(conn: psycopg.Connection) -> list[QueueEntry]:
    return [to_entry(row) for row in conn.execute(QUEUE_SQL).fetchall()]


def sse(event: str, entries: list[QueueEntry]) -> str:
    data = json.dumps([entry.model_dump(mode="json") for entry in entries])
    return f"event: {event}\ndata: {data}\n\n"


async def queue_events(
    connect: Callable[[], Awaitable[psycopg.AsyncConnection]],
    is_disconnected: Callable[[], Awaitable[bool]],
    heartbeat_seconds: float = 15.0,
) -> AsyncIterator[str]:
    """Server-Sent Events: the full queue on connect, then again after every change.

    Changes arrive as Postgres NOTIFY messages (see the triggers in db/schema.sql), so this works
    with any number of service replicas. A comment line every heartbeat keeps proxies from
    closing an idle connection.
    """
    async with await connect() as conn:
        await conn.execute("LISTEN queue_changed")

        async def snapshot() -> str:
            cur = await conn.execute(QUEUE_SQL)
            return sse("queue", [to_entry(row) for row in await cur.fetchall()])

        yield await snapshot()
        while not await is_disconnected():
            changed = False
            async for _ in conn.notifies(timeout=heartbeat_seconds, stop_after=1):
                changed = True
            yield await snapshot() if changed else ": keep-alive\n\n"
