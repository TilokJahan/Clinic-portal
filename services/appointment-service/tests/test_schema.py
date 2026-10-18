from pathlib import Path

import psycopg
import pytest
from psycopg import errors

DB_DIR = Path(__file__).resolve().parent.parent / "db"


def _add_provider(db) -> int:
    return db.execute(
        "INSERT INTO providers (name, specialty) VALUES ('Dr. Test', 'General Practice') "
        "RETURNING id"
    ).fetchone()[0]


def _add_slot(db, provider_id: int, starts_at: str = "2030-01-07 09:00+00") -> int:
    return db.execute(
        "INSERT INTO slots (provider_id, starts_at, ends_at) "
        "VALUES (%s, %s, %s::timestamptz + interval '30 minutes') RETURNING id",
        (provider_id, starts_at, starts_at),
    ).fetchone()[0]


def _add_patient(db, email: str = "p@example.com") -> int:
    return db.execute(
        "INSERT INTO users (email, role) VALUES (%s, 'patient') RETURNING id", (email,)
    ).fetchone()[0]


def test_seed_loads_cleanly(db):
    db.execute((DB_DIR / "seed.sql").read_text())
    assert db.execute("SELECT count(*) FROM providers").fetchone()[0] == 3
    assert db.execute("SELECT count(*) FROM slots").fetchone()[0] > 0
    future = db.execute("SELECT bool_and(starts_at > now()) FROM slots").fetchone()[0]
    assert future


def test_same_provider_and_time_slot_is_rejected(db):
    provider_id = _add_provider(db)
    _add_slot(db, provider_id)
    with pytest.raises(errors.UniqueViolation):
        _add_slot(db, provider_id)


def test_same_slot_cannot_be_booked_twice(db):
    slot_id = _add_slot(db, _add_provider(db))
    first, second = _add_patient(db, "a@example.com"), _add_patient(db, "b@example.com")
    db.execute("INSERT INTO appointments (patient_id, slot_id) VALUES (%s, %s)", (first, slot_id))
    with pytest.raises(errors.UniqueViolation):
        db.execute(
            "INSERT INTO appointments (patient_id, slot_id) VALUES (%s, %s)", (second, slot_id)
        )


def test_cancelled_slot_can_be_booked_again(db):
    slot_id = _add_slot(db, _add_provider(db))
    first, second = _add_patient(db, "a@example.com"), _add_patient(db, "b@example.com")
    db.execute(
        "INSERT INTO appointments (patient_id, slot_id, status) VALUES (%s, %s, 'cancelled')",
        (first, slot_id),
    )
    db.execute("INSERT INTO appointments (patient_id, slot_id) VALUES (%s, %s)", (second, slot_id))
    with pytest.raises(errors.UniqueViolation):
        db.execute(
            "INSERT INTO appointments (patient_id, slot_id) VALUES (%s, %s)", (first, slot_id)
        )


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO users (email, role) VALUES ('x@example.com', 'superuser')",
        "INSERT INTO slots (provider_id, starts_at, ends_at) VALUES (999, now(), now() + '1h')",
        "INSERT INTO appointments (patient_id, slot_id) VALUES (999, 999)",
    ],
    ids=["invalid-role", "unknown-provider", "unknown-patient-and-slot"],
)
def test_invalid_rows_are_rejected(db, sql):
    with pytest.raises(psycopg.IntegrityError):
        db.execute(sql)


def test_slot_must_end_after_it_starts(db):
    provider_id = _add_provider(db)
    with pytest.raises(errors.CheckViolation):
        db.execute(
            "INSERT INTO slots (provider_id, starts_at, ends_at) VALUES (%s, now(), now())",
            (provider_id,),
        )
