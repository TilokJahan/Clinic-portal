-- Lab technician role (schema v3). Safe to run more than once, so the db-init Job applies it to
-- existing databases too. Runs after schemav2_lab_results.sql and before seed.sql (the name sorts
-- between them both in C and en_US order, which docker's init uses).

ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check
    CHECK (role IN ('patient', 'clinician', 'admin', 'lab_tech'));

-- Demo lab technician for databases that already exist. On a brand-new database the users table
-- is still empty here, so nothing is inserted: seed.sql adds this user itself, last, which keeps
-- the other demo users' ids (1-5) unchanged.
INSERT INTO users (email, role)
SELECT 'labtech1@example.com', 'lab_tech'
WHERE EXISTS (SELECT 1 FROM users)
ON CONFLICT (email) DO NOTHING;
