-- Symptoms first, and several proposed times (schema v8). Safe to run more than once, so the
-- db-init Job applies it to existing databases too. Runs after schemav7_approval.sql and before
-- seed.sql (the name sorts between them both in C and en_US order, which docker's init uses).
--
-- 1. The patient describes their symptoms before choosing a time, so the urgency can limit which
--    times they may pick. That triage result belongs to the patient until the booking links it
--    to an appointment (POST /assessments, then POST /appointments with assessment_id).
-- 2. A clinician can propose up to three times at once (enforced in app/reschedule.py). The
--    patient accepts one, chooses another time themselves, or answers that none of them work,
--    with a note the clinician reads.

ALTER TABLE triage_results ADD COLUMN IF NOT EXISTS patient_id BIGINT REFERENCES users (id);
ALTER TABLE triage_results ALTER COLUMN appointment_id DROP NOT NULL;
UPDATE triage_results t SET patient_id = a.patient_id
FROM appointments a
WHERE a.id = t.appointment_id AND t.patient_id IS NULL;
CREATE INDEX IF NOT EXISTS triage_results_unlinked_idx ON triage_results (patient_id)
    WHERE appointment_id IS NULL;

-- Several pending proposals per appointment instead of one
DROP INDEX IF EXISTS reschedule_offers_one_pending;
CREATE INDEX IF NOT EXISTS reschedule_offers_pending_idx ON reschedule_offers (appointment_id)
    WHERE status = 'pending';
-- Why the patient said none of the proposed times work. Written by the patient, for the clinician.
ALTER TABLE reschedule_offers ADD COLUMN IF NOT EXISTS patient_note TEXT
    CHECK (char_length(patient_note) <= 500);
