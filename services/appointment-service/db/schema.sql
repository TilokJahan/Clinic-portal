-- Clinic portal schema, v1 (PostgreSQL 16).
-- Runs on a fresh database. docker-compose loads this automatically on first start
-- (files in db/ are mounted into /docker-entrypoint-initdb.d and run in name order).
-- Synthetic data only: never load real patient information.

CREATE TABLE users (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email       TEXT        NOT NULL UNIQUE,
    role        TEXT        NOT NULL CHECK (role IN ('patient', 'clinician', 'admin')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE providers (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT        NOT NULL,
    specialty   TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE slots (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider_id  BIGINT      NOT NULL REFERENCES providers (id) ON DELETE CASCADE,
    starts_at    TIMESTAMPTZ NOT NULL,
    ends_at      TIMESTAMPTZ NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT slots_provider_starts_at_key UNIQUE (provider_id, starts_at),
    CONSTRAINT slots_ends_after_starts CHECK (ends_at > starts_at)
);

CREATE INDEX slots_starts_at_idx ON slots (starts_at);

CREATE TABLE appointments (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    patient_id  BIGINT      NOT NULL REFERENCES users (id),
    slot_id     BIGINT      NOT NULL REFERENCES slots (id),
    status      TEXT        NOT NULL DEFAULT 'booked'
                CHECK (status IN ('booked', 'checked_in', 'completed', 'cancelled')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- At most one non-cancelled appointment per slot. This index is what prevents double booking,
-- even when two requests race each other. Cancelled rows are ignored, so a cancelled slot can
-- be booked again while its history is kept.
CREATE UNIQUE INDEX appointments_active_slot_key ON appointments (slot_id)
    WHERE status <> 'cancelled';

CREATE INDEX appointments_patient_id_idx ON appointments (patient_id);

CREATE TABLE triage_results (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    appointment_id       BIGINT      NOT NULL REFERENCES appointments (id) ON DELETE CASCADE,
    -- What the AI suggested (see "Triage result" in docs/api.md)
    ai_urgency           TEXT        NOT NULL CHECK (ai_urgency IN ('routine', 'soon', 'urgent')),
    suggested_specialty  TEXT,
    red_flags            TEXT[]      NOT NULL DEFAULT '{}',
    summary              TEXT        NOT NULL,
    -- What the clinician decided. NULL until reviewed.
    final_urgency        TEXT        CHECK (final_urgency IN ('routine', 'soon', 'urgent')),
    overridden           BOOLEAN     NOT NULL DEFAULT false,
    -- Metrics for the AI call
    latency_ms           INTEGER     CHECK (latency_ms >= 0),
    tokens_used          INTEGER     CHECK (tokens_used >= 0),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX triage_results_appointment_id_idx ON triage_results (appointment_id);
