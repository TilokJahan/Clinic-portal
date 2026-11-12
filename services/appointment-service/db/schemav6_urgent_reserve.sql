-- Urgent reserve (schema v6). Safe to run more than once: the db-init Job runs it on every deploy,
-- which also keeps two weeks of slots open ahead. Runs after schemav5_reschedule.sql and before
-- seed.sql (the name sorts between them both in C and en_US order, which docker's init uses).
--
-- Each provider keeps one 30-minute slot a day free for urgent patients (see app/urgency.py).
-- Urgent patients and clinician offers can always use it. Ordinary patients can fill it on its own
-- day, while no urgent patient is waiting (OPEN_TO_ALL in app/urgency.py).

ALTER TABLE slots ADD COLUMN IF NOT EXISTS reserved_for_urgent BOOLEAN NOT NULL DEFAULT false;

-- Which slot is the reserve. The demo day has six 30-minute slots from 14:00 UTC (9:00 US Eastern
-- standard time). Each provider's reserve is at a different time, and it moves on by one slot each
-- day, so urgent patients have a choice of times across the morning: with three providers on one
-- day, for example 9:30, 10:00 and 10:30.
CREATE OR REPLACE FUNCTION is_urgent_reserve(provider BIGINT, starts TIMESTAMPTZ)
RETURNS BOOLEAN LANGUAGE sql IMMUTABLE AS $$
    SELECT (starts AT TIME ZONE 'UTC')::time = time '14:00'
        + ((provider + ((starts AT TIME ZONE 'UTC')::date - date '2000-01-01')) % 6)
          * interval '30 minutes'
$$;

-- Existing future slots nobody has booked; past and booked ones are history
UPDATE slots s SET reserved_for_urgent = true
WHERE s.starts_at > now() AND NOT s.reserved_for_urgent
  AND is_urgent_reserve(s.provider_id, s.starts_at)
  AND NOT EXISTS (
      SELECT 1 FROM appointments a WHERE a.slot_id = s.id AND a.status <> 'cancelled'
  );

-- Keep the next 14 days of slots open, the same schedule as seed.sql. On a fresh database there
-- are no providers yet at this point, so this adds nothing and seed.sql creates the slots.
INSERT INTO slots (provider_id, starts_at, ends_at, reserved_for_urgent)
SELECT p.id, s.starts_at, s.starts_at + interval '30 minutes', is_urgent_reserve(p.id, s.starts_at)
FROM providers p
CROSS JOIN LATERAL (
    SELECT (d + interval '14 hours' + n * interval '30 minutes') AT TIME ZONE 'UTC' AS starts_at
    FROM generate_series(
        (current_date + 1)::timestamp, (current_date + 14)::timestamp, interval '1 day'
    ) AS d
    CROSS JOIN generate_series(0, 5) AS n
    WHERE extract(isodow FROM d) < 6
) s
ON CONFLICT ON CONSTRAINT slots_provider_starts_at_key DO NOTHING;
