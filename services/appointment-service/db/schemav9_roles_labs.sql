-- Physicians, lab requests, more kinds of tests and visit summaries (schema v9). Safe to run more
-- than once, so the db-init Job applies it to existing databases too. Runs after
-- schemav8_booking_flow.sql and before seed.sql (the name sorts between them both in C and en_US
-- order, which docker's init uses).

-- 1. A physician (doctor) role. A physician is linked to the provider whose schedule they see.
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check
    CHECK (role IN ('patient', 'clinician', 'physician', 'admin', 'lab_tech'));
ALTER TABLE users ADD COLUMN IF NOT EXISTS provider_id BIGINT REFERENCES providers (id);

-- Demo physicians for databases that already exist (a brand-new database gets them from seed.sql,
-- after the providers exist)
INSERT INTO users (email, role, provider_id)
SELECT v.email, 'physician', p.id
FROM (VALUES ('physician1@example.com', 'Dr. Alex Example'),
             ('physician2@example.com', 'Dr. Sam Sample'),
             ('physician3@example.com', 'Dr. Jordan Test')) AS v (email, provider)
JOIN providers p ON p.name = v.provider
WHERE EXISTS (SELECT 1 FROM users)
ON CONFLICT (email) DO NOTHING;

-- 2. Tests the symptoms suggest, from fixed rules (app/lab_needs.py), e.g. {blood, ultrasound}
ALTER TABLE triage_results ADD COLUMN IF NOT EXISTS suggested_tests TEXT[] NOT NULL DEFAULT '{}';

-- 3. Not only blood tests: what kind of test a report is, and when it was taken. Imaging and
--    ECG reports have no table of values; a clinician reads them.
ALTER TABLE lab_reports ADD COLUMN IF NOT EXISTS exam_type TEXT NOT NULL DEFAULT 'blood'
    CHECK (exam_type IN ('blood', 'urine', 'ultrasound', 'xray', 'ct', 'mri', 'ecg', 'other'));
ALTER TABLE lab_reports ADD COLUMN IF NOT EXISTS taken_on DATE;

-- 4. A clinician or physician asks the lab for a test; the lab technician sees it with its urgency
CREATE TABLE IF NOT EXISTS lab_requests (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    appointment_id  BIGINT      NOT NULL REFERENCES appointments (id) ON DELETE CASCADE,
    exam_type       TEXT        NOT NULL
                    CHECK (exam_type IN ('blood', 'urine', 'ultrasound', 'xray', 'ct', 'mri', 'ecg', 'other')),
    urgency         TEXT        NOT NULL CHECK (urgency IN ('routine', 'soon', 'urgent')),
    -- For the lab (what to test, why). Not shown to the patient.
    note            TEXT        CHECK (char_length(note) <= 500),
    status          TEXT        NOT NULL DEFAULT 'requested'
                    CHECK (status IN ('requested', 'scheduled', 'completed', 'cancelled')),
    requested_by    BIGINT      NOT NULL REFERENCES users (id),
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    report_id       BIGINT      REFERENCES lab_reports (id)
);
CREATE INDEX IF NOT EXISTS lab_requests_appointment_idx ON lab_requests (appointment_id);
CREATE INDEX IF NOT EXISTS lab_requests_open_idx ON lab_requests (status)
    WHERE status IN ('requested', 'scheduled');
DROP TRIGGER IF EXISTS lab_requests_queue_changed ON lab_requests;
CREATE TRIGGER lab_requests_queue_changed
    AFTER INSERT OR UPDATE OR DELETE ON lab_requests
    FOR EACH STATEMENT EXECUTE FUNCTION notify_queue_changed();

-- 5. The physician's summary of the visit, for the patient, when they complete it
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS visit_summary TEXT
    CHECK (char_length(visit_summary) <= 3000);
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE appointments ADD COLUMN IF NOT EXISTS completed_by BIGINT REFERENCES users (id);
