# API Contract (v0, edit via pull request)

Agree on this first so the frontend can mock against it while the backend is built.
All endpoints except `/health` require `Authorization: Bearer <JWT>` once auth is in place.
Roles: `patient`, `clinician`, `admin`.

| Method | Path | Service | Role | Purpose |
|---|---|---|---|---|
| GET | `/health` | all | none | Liveness check |
| GET | `/slots?date=YYYY-MM-DD&provider_id=` | appointment | patient | List available slots |
| POST | `/appointments` | appointment | patient | Book a slot |
| POST | `/intake` | appointment | patient | Submit symptoms (calls triage-service) |
| GET | `/queue` | appointment | clinician | Waiting patients, sorted by urgency |
| GET | `/queue/stream` | appointment | clinician | Server-Sent Events for live updates |
| POST | `/triage` | triage | internal | Redact PII, call AI, return structured result |
| PATCH | `/triage/{id}` | appointment | clinician | Accept or override the AI result |

## Slots and booking (implemented, no auth yet)

All times are ISO 8601 in UTC.

`GET /slots?date=2030-01-07&provider_id=1`: `date` is required, `provider_id` is optional.
Returns free slots that start on that day and haven't started yet, earliest first. A slot whose
only appointments are cancelled counts as free.

```json
[{"id": 1, "provider_id": 1, "starts_at": "2030-01-07T09:00:00Z", "ends_at": "2030-01-07T09:30:00Z"}]
```

`POST /appointments` with body `{"patient_id": 1, "slot_id": 1}`. `patient_id` moves to the JWT
once auth is in place.

| Status | When | Body |
|---|---|---|
| 201 | Booked | `{"id": 1, "patient_id": 1, "slot_id": 1, "status": "booked", "created_at": "..."}` |
| 404 | Unknown slot, or the user isn't a patient | `{"detail": "Slot not found"}` / `{"detail": "Patient not found"}` |
| 409 | Slot already booked, or already started | `{"detail": "Slot is already booked"}` / `{"detail": "Slot has already started"}` |
| 422 | Invalid body | FastAPI validation error |

## Triage result (JSON)

```json
{
  "urgency": "routine | soon | urgent",
  "suggested_specialty": "General Practice",
  "red_flags": ["..."],
  "summary": "One paragraph for the clinician."
}
```

## Core tables (draft)

- `users` (id, email, role)
- `providers` (id, name, specialty)
- `slots` (id, provider_id, starts_at, ends_at) with UNIQUE (provider_id, starts_at)
- `appointments` (id, patient_id, slot_id UNIQUE, status, created_at)
- `triage_results` (id, appointment_id, ai_urgency, final_urgency, overridden, summary,
  latency_ms, tokens_used, created_at)
