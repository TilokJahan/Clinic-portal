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
