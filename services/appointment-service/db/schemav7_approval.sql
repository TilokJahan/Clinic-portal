-- Clinician approval of bookings (schema v7). Safe to run more than once, so the db-init Job
-- applies it to existing databases too. Runs after schemav6_urgent_reserve.sql and before
-- seed.sql (the name sorts between them both in C and en_US order, which docker's init uses).
--
-- A patient requests a time and describes their symptoms; the slot is held while the request
-- waits. A clinician looks at the symptoms and urgency, then approves the request, declines it,
-- or offers a different time (see app/approval.py). A booked visit with approved_at NULL is a
-- request waiting for approval.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'appointments'
          AND column_name = 'approved_at'
    ) THEN
        ALTER TABLE appointments
            ADD COLUMN approved_at    TIMESTAMPTZ,
            ADD COLUMN approved_by    BIGINT REFERENCES users (id),
            -- Set when a clinician declines a request (status becomes 'cancelled')
            ADD COLUMN declined_at    TIMESTAMPTZ,
            -- Shown to the patient, so it must not hold anything the patient shouldn't read
            ADD COLUMN decline_reason TEXT CHECK (char_length(decline_reason) <= 500);
        -- Bookings made before approval existed count as approved. Only done once, when the
        -- column is added, so later runs never approve a waiting request.
        UPDATE appointments SET approved_at = created_at WHERE status <> 'cancelled';
    END IF;
END $$;
