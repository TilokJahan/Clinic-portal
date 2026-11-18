-- Lab visits and admin invitations (schema v10, named v9z so it sorts right after
-- schemav9_roles_labs.sql and before seed.sql in both C and en_US order, which docker's init uses; "schemav10" would sort before
-- "schemav2"). Safe to run more than once, so the db-init Job applies it to existing databases.
--
-- After a clinician or physician asks for a test, the lab technician proposes up to three times
-- for the patient to come to the lab, as soon as the urgency needs. The patient accepts one or
-- chooses another free lab time (app/lab_visits.py).

DO $$
BEGIN
    ALTER TABLE lab_requests DROP CONSTRAINT IF EXISTS lab_requests_status_check;
    ALTER TABLE lab_requests ADD CONSTRAINT lab_requests_status_check
        CHECK (status IN ('requested', 'proposed', 'scheduled', 'completed', 'cancelled'));
    -- The times the lab proposed, and the time the patient chose
    ALTER TABLE lab_requests ADD COLUMN IF NOT EXISTS proposed_times TIMESTAMPTZ[] NOT NULL
        DEFAULT '{}';
    ALTER TABLE lab_requests ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMPTZ;
    -- The lab sees one patient at a time: two patients can never get the same lab time, even
    -- when they choose at the same moment
    CREATE UNIQUE INDEX IF NOT EXISTS lab_requests_one_per_time
        ON lab_requests (scheduled_at) WHERE status = 'scheduled';
END $$;

-- Admin invitations and account control (same release as lab visits). The admin invites someone
-- by email with a role; the invite link lets them register with that role. An admin can also
-- disable an account: a disabled user can't sign in or use a token they already have.
ALTER TABLE users ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT true;
CREATE TABLE IF NOT EXISTS invitations (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email            TEXT        NOT NULL CHECK (email = lower(email) AND email LIKE '%_@_%'),
    role             TEXT        NOT NULL
                     CHECK (role IN ('patient', 'clinician', 'physician', 'admin', 'lab_tech')),
    provider_id      BIGINT      REFERENCES providers (id),
    -- The secret in the invite link (random, URL-safe); whoever has the link can register
    token            TEXT        NOT NULL UNIQUE,
    invited_by       BIGINT      NOT NULL REFERENCES users (id),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at       TIMESTAMPTZ NOT NULL,
    accepted_at      TIMESTAMPTZ,
    accepted_user_id BIGINT      REFERENCES users (id),
    revoked_at       TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS invitations_email_idx ON invitations (email);
