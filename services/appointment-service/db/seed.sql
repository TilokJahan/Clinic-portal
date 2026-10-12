-- Synthetic seed data for local development. NO real people or patient data.
-- Emails use the reserved example.com domain. Runs after schema.sql on a fresh database.

INSERT INTO users (email, role) VALUES
    ('patient1@example.com', 'patient'),
    ('patient2@example.com', 'patient'),
    ('patient3@example.com', 'patient'),
    ('clinician1@example.com', 'clinician'),
    ('admin1@example.com', 'admin');

INSERT INTO providers (name, specialty) VALUES
    ('Dr. Alex Example', 'General Practice'),
    ('Dr. Sam Sample', 'Dermatology'),
    ('Dr. Jordan Test', 'Cardiology');

-- 30-minute slots, 09:00-12:00 UTC, on weekdays for the next 14 days, for every provider.
-- Relative to the current date so a fresh database always has bookable future slots.
INSERT INTO slots (provider_id, starts_at, ends_at)
SELECT p.id, s.starts_at, s.starts_at + interval '30 minutes'
FROM providers p
CROSS JOIN LATERAL (
    SELECT (d + interval '9 hours' + n * interval '30 minutes') AT TIME ZONE 'UTC' AS starts_at
    FROM generate_series(
        (current_date + 1)::timestamp, (current_date + 14)::timestamp, interval '1 day'
    ) AS d
    CROSS JOIN generate_series(0, 5) AS n
    WHERE extract(isodow FROM d) < 6
) s;
