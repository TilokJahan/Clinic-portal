# API Contract (v1, edit via pull request)

Every change to this file goes through a pull request that all three of us review (#10).

| Method | Path | Service | Role | Purpose | Status |
|---|---|---|---|---|---|
| GET | `/health` | all | none | Liveness check | done |
| GET | `/slots?date=YYYY-MM-DD&provider_id=` | appointment | patient | List free slots | done |
| POST | `/appointments` | appointment | patient | Book a slot | done |
| POST | `/intake` | appointment | patient | Submit symptoms (calls triage-service) | done |
| GET | `/queue` | appointment | clinician | Waiting patients, most urgent first | done |
| GET | `/queue/stream` | appointment | clinician | Server-Sent Events for live updates | done |
| PATCH | `/triage/{id}` | appointment | clinician | Accept or override the AI result | done |
| POST | `/triage` | triage | internal | Redact PII, call AI, return structured result | done |

## Conventions

- **JSON** everywhere. Field names are `snake_case`.
- **Times** are ISO 8601 strings in UTC, for example `"2030-01-07T09:00:00Z"`. The frontend
  converts to local time for display.
- **IDs** are integers.
- **Errors** use FastAPI's shape: `{"detail": "Slot is already booked"}`. Validation errors
  (status 422) have a list in `detail`.
- **Who calls whom:** the browser only talks to the appointment service. The appointment service
  calls the triage service (`TRIAGE_SERVICE_URL`). The triage service is never exposed publicly.
- **Privacy:** the queue shows a label such as `"Patient 0002"`, not names or emails. Symptom
  text is passed to the triage service (which redacts it before the AI) and is **not stored**;
  only the structured triage result is.
- **Auth (not built yet):** the frontend will send `Authorization: Bearer <JWT>`. Roles are
  `patient`, `clinician`, `admin`. Patients will get 401 without a token and 403 on clinician
  endpoints. Until then, `patient_id` is sent in the body of `POST /appointments` and will move
  into the token.

## Shared shapes

**Slot**

```json
{"id": 1, "provider_id": 1, "starts_at": "2030-01-07T09:00:00Z", "ends_at": "2030-01-07T09:30:00Z"}
```

**Appointment**

```json
{"id": 7, "patient_id": 1, "slot_id": 1, "status": "booked", "created_at": "2030-01-06T15:02:11Z"}
```

`status` is one of `booked`, `checked_in`, `completed`, `cancelled`.

**TriageRecord** (a stored triage result)

```json
{
  "id": 3,
  "appointment_id": 7,
  "ai_urgency": "urgent",
  "final_urgency": null,
  "urgency": "urgent",
  "overridden": false,
  "suggested_specialty": "Emergency Medicine",
  "red_flags": ["possible cardiac or respiratory emergency"],
  "summary": "Potentially serious symptom reported. Clinician review needed now.",
  "latency_ms": 41,
  "created_at": "2030-01-06T15:05:00Z",
  "reviewed_at": null
}
```

- `ai_urgency`: what the AI suggested. `final_urgency`: what the clinician chose, `null` until
  reviewed. `urgency`: the one to display (`final_urgency` if set, otherwise `ai_urgency`).
- `overridden` is `true` when the clinician chose a different urgency from the AI.
- Urgency is always one of `routine`, `soon`, `urgent`.

**QueueEntry**

```json
{
  "appointment_id": 7,
  "patient_label": "Patient 0001",
  "provider_id": 1,
  "provider_name": "Dr. Alex Example",
  "starts_at": "2030-01-07T09:00:00Z",
  "status": "booked",
  "booked_at": "2030-01-06T15:02:11Z",
  "triage": { "...": "TriageRecord, or null before the patient submits an intake" }
}
```

## Endpoints

### `GET /slots?date=2030-01-07&provider_id=1`

`date` is required, `provider_id` is optional. Returns `Slot[]`: free slots that start on that
UTC day and haven't started yet, earliest first. A slot whose only appointments are cancelled
counts as free.

| Status | When |
|---|---|
| 200 | Always, possibly `[]` |
| 422 | Missing or invalid `date`, or `provider_id` < 1 |

### `POST /appointments`

Body `{"patient_id": 1, "slot_id": 1}`. Returns the `Appointment`.

| Status | When | Body |
|---|---|---|
| 201 | Booked | `Appointment` |
| 404 | Unknown slot, or the user isn't a patient | `{"detail": "Slot not found"}` / `{"detail": "Patient not found"}` |
| 409 | Slot already booked, or already started | `{"detail": "Slot is already booked"}` / `{"detail": "Slot has already started"}` |
| 422 | Invalid body | validation error |

### `POST /intake`

Body `{"appointment_id": 7, "symptoms": "Chest pain since this morning"}`. `symptoms` is 1 to
4000 characters. The appointment service sends the text to the triage service, stores the result
and returns it. One intake per appointment.

| Status | When | Body |
|---|---|---|
| 201 | Triaged and stored | `TriageRecord` |
| 404 | Unknown appointment | `{"detail": "Appointment not found"}` |
| 409 | Appointment is cancelled, or already has an intake | `{"detail": "Appointment is cancelled"}` / `{"detail": "Intake already submitted"}` |
| 422 | Invalid body | validation error |

If the triage service is down or returns something invalid, the intake still succeeds with a
safe fallback: `urgency: "soon"` and a summary saying a clinician should review manually.

### `GET /queue`

Returns `QueueEntry[]` for appointments that are `booked` or `checked_in`. Order: `urgent`, then
`soon`, then `routine`; within the same urgency, whoever submitted their intake first; patients
without an intake come last, by appointment time.

### `GET /queue/stream`

[Server-Sent Events](https://developer.mozilla.org/docs/Web/API/Server-sent_events)
(`text/event-stream`). Use `new EventSource("/queue/stream")` in the browser.

- On connect, and again after **any** change to appointments or triage results, the server sends
  the whole queue: `event: queue` with `data:` set to the same JSON array as `GET /queue`.
- When nothing changes for 15 seconds it sends a comment line (`: keep-alive`), which
  `EventSource` ignores.
- Changes are delivered through Postgres `LISTEN/NOTIFY`, so this works with several replicas.

### `PATCH /triage/{id}`

Body `{"final_urgency": "soon"}`. Sending the AI's own urgency means "accept"; anything else is an
override. Returns the updated `TriageRecord` with `reviewed_at` set.

| Status | When |
|---|---|
| 200 | Saved |
| 404 | Unknown triage id (`{"detail": "Triage result not found"}`) |
| 422 | `final_urgency` isn't `routine`, `soon` or `urgent` |

### `POST /triage` (triage service, internal)

Body `{"symptoms": "..."}` (1 to 4000 characters). Redacts personal details, then asks the AI
client. Returns:

```json
{
  "urgency": "routine | soon | urgent",
  "suggested_specialty": "General Practice",
  "red_flags": ["..."],
  "summary": "One paragraph for the clinician."
}
```

## Tables

See [schema.md](schema.md) for the full schema and the rules the database enforces.
