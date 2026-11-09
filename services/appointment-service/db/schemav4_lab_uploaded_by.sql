-- Who uploaded a lab report (schema v4). Safe to run more than once, so the db-init Job applies
-- it to existing databases too. Runs after schemav3_lab_tech.sql and before seed.sql (the name
-- sorts between them both in C and en_US order, which docker's init uses).

ALTER TABLE lab_reports ADD COLUMN IF NOT EXISTS uploaded_by BIGINT REFERENCES users (id);

-- Until now only the patient could upload, so older reports belong to the appointment's patient.
UPDATE lab_reports r SET uploaded_by = a.patient_id
FROM appointments a
WHERE a.id = r.appointment_id AND r.uploaded_by IS NULL;
