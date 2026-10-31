-- Lab reports and their extracted results (schema v2). Safe to run more than once, so the
-- db-init Job applies it to existing databases too. Runs after schema.sql, before seed.sql
-- (the name sorts between them both in C and en_US order, which docker's init uses).

CREATE TABLE IF NOT EXISTS lab_reports (
    id                       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    appointment_id           BIGINT      NOT NULL REFERENCES appointments (id) ON DELETE CASCADE,
    -- Where the file is (Blob Storage or a local folder). The original file name is not kept:
    -- it often contains the patient's name.
    blob_name                TEXT        NOT NULL UNIQUE,
    content_type             TEXT        NOT NULL
                             CHECK (content_type IN ('application/pdf', 'image/png', 'image/jpeg')),
    size_bytes               INTEGER     NOT NULL CHECK (size_bytes > 0),
    status                   TEXT        NOT NULL DEFAULT 'processing'
                             CHECK (status IN ('processing', 'ready', 'needs_review', 'failed')),
    -- From fixed rules (critical values) and the AI, which can raise but never lower it
    lab_urgency              TEXT        CHECK (lab_urgency IN ('routine', 'soon', 'urgent')),
    reason                   TEXT,
    clinician_summary        TEXT,
    -- AI draft until a clinician approves (and possibly edits) it; patients see it only after
    patient_explanation      TEXT,
    explanation_approved_at  TIMESTAMPTZ,
    explanation_approved_by  BIGINT      REFERENCES users (id),
    extraction_confidence    REAL        CHECK (extraction_confidence BETWEEN 0 AND 1),
    tokens_used              INTEGER     CHECK (tokens_used >= 0),
    latency_ms               INTEGER     CHECK (latency_ms >= 0),
    uploaded_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at             TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS lab_reports_appointment_id_idx ON lab_reports (appointment_id);

CREATE TABLE IF NOT EXISTS lab_results (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_id            BIGINT  NOT NULL REFERENCES lab_reports (id) ON DELETE CASCADE,
    test_name            TEXT    NOT NULL, -- as printed on the report
    display_name         TEXT    NOT NULL,
    canonical            TEXT,             -- e.g. "potassium"; NULL for tests we don't map
    value                NUMERIC,          -- in the canonical unit when the test is mapped
    unit                 TEXT    NOT NULL DEFAULT '',
    ref_low              NUMERIC,
    ref_high             NUMERIC,
    flag                 TEXT    NOT NULL
                         CHECK (flag IN ('normal', 'low', 'high', 'critical_low', 'critical_high',
                                         'unknown')),
    confidence           REAL    CHECK (confidence BETWEEN 0 AND 1),
    needs_verification   BOOLEAN NOT NULL DEFAULT false,
    verification_reason  TEXT
);

CREATE INDEX IF NOT EXISTS lab_results_report_id_idx ON lab_results (report_id);
-- Results over time for one test (e.g. a patient's potassium history)
CREATE INDEX IF NOT EXISTS lab_results_canonical_idx ON lab_results (canonical);

-- Lab changes update the clinicians' live queue, like appointments and triage results
DROP TRIGGER IF EXISTS lab_reports_queue_changed ON lab_reports;
CREATE TRIGGER lab_reports_queue_changed
    AFTER INSERT OR UPDATE OR DELETE ON lab_reports
    FOR EACH STATEMENT EXECUTE FUNCTION notify_queue_changed();
