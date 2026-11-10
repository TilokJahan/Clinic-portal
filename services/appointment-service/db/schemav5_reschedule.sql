-- Earlier-visit offers (schema v5). Safe to run more than once, so the db-init Job applies it to
-- existing databases too. Runs after schemav4_lab_uploaded_by.sql and before seed.sql (the name
-- sorts between them both in C and en_US order, which docker's init uses).
--
-- A clinician offers an urgent patient an earlier free slot. Nothing moves until the patient
-- accepts (see app/reschedule.py).

CREATE TABLE IF NOT EXISTS reschedule_offers (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    appointment_id    BIGINT      NOT NULL REFERENCES appointments (id) ON DELETE CASCADE,
    proposed_slot_id  BIGINT      NOT NULL REFERENCES slots (id),
    offered_by        BIGINT      NOT NULL REFERENCES users (id),
    -- Written by the clinician for the care team. Never shown to the patient.
    reason            TEXT,
    status            TEXT        NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'accepted', 'declined', 'expired')),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    responded_at      TIMESTAMPTZ
);

-- One open offer per appointment, even when two clinicians click at the same time
CREATE UNIQUE INDEX IF NOT EXISTS reschedule_offers_one_pending
    ON reschedule_offers (appointment_id) WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS reschedule_offers_slot_idx ON reschedule_offers (proposed_slot_id);

-- Live queue: sending or answering an offer changes what the clinician screen shows
DROP TRIGGER IF EXISTS reschedule_offers_queue_changed ON reschedule_offers;
CREATE TRIGGER reschedule_offers_queue_changed
    AFTER INSERT OR UPDATE OR DELETE ON reschedule_offers
    FOR EACH STATEMENT EXECUTE FUNCTION notify_queue_changed();
