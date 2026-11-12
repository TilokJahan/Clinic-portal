-- Urgent reserve (schema v6). Safe to run more than once: the db-init Job runs it on every deploy,
-- which also keeps two weeks of slots open ahead. Runs after schemav5_reschedule.sql and before
-- seed.sql (the name sorts between them both in C and en_US order, which docker's init uses).
--
-- Each provider keeps the last slot of each day free for urgent patients (see app/urgency.py).
-- Ordinary booking can't take it; urgent patients and clinician offers can. If nobody urgent needs
-- it, it opens to everyone shortly before it starts, so it isn't wasted.

ALTER TABLE slots ADD COLUMN IF NOT EXISTS reserved_for_urgent BOOLEAN NOT NULL DEFAULT false;

-- The last slot of the day (16:30 UTC, 11:30 US Eastern standard time) in the demo schedule.
-- Only future slots nobody has booked; past and booked ones are history.
UPDATE slots s SET reserved_for_urgent = true
WHERE s.starts_at > now() AND s.starts_at::time = time '16:30' AND NOT s.reserved_for_urgent
  AND NOT EXISTS (
      SELECT 1 FROM appointments a WHERE a.slot_id = s.id AND a.status <> 'cancelled'
  );

-- Keep the next 14 days of slots open, the same schedule as seed.sql. On a fresh database there
-- are no providers yet at this point, so this adds nothing and seed.sql creates the slots.
INSERT INTO slots (provider_id, starts_at, ends_at, reserved_for_urgent)
SELECT p.id, s.starts_at, s.starts_at + interval '30 minutes', s.n = 5
FROM providers p
CROSS JOIN LATERAL (
    SELECT (d + interval '14 hours' + n * interval '30 minutes') AT TIME ZONE 'UTC' AS starts_at, n
    FROM generate_series(
        (current_date + 1)::timestamp, (current_date + 14)::timestamp, interval '1 day'
    ) AS d
    CROSS JOIN generate_series(0, 5) AS n
    WHERE extract(isodow FROM d) < 6
) s
ON CONFLICT ON CONSTRAINT slots_provider_starts_at_key DO NOTHING;
