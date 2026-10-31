# API Contract (v2, edit via pull request)

Every change to this file goes through a pull request that all three of us review (#10).

| Method | Path | Service | Role | Purpose | Status |
|---|---|---|---|---|---|
| GET | `/health` | all | none | Liveness check | done |
| POST | `/auth/dev-login` | appointment | none (dev only) | Demo token for a seed account | done |
| GET | `/me` | appointment | any | The signed-in user | done |
| GET | `/slots?date=YYYY-MM-DD&provider_id=` | appointment | any | List free slots | done |
| POST | `/appointments` | appointment | patient | Book a slot | done |
| GET | `/appointments` | appointment | patient | My bookings | done |
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
- **Auth:** every endpoint except `/health` and `/auth/dev-login` needs
  `Authorization: Bearer <token>`. Roles are `patient`, `clinician`, `admin` (admin can do
  everything a clinician can). See [Authentication](#authentication).

## Shared shapes

**Slot**

```json
{"id": 1, "provider_id": 1, "provider_name": "Dr. Alex Example", "specialty": "General Practice",
 "starts_at": "2030-01-07T09:00:00Z", "ends_at": "2030-01-07T09:30:00Z"}
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
  "tokens_used": 512,
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

## Authentication

The backend's `AUTH_MODE` picks how tokens are issued; the endpoints work the same either way.

| Mode | Where | How you get a token |
|---|---|---|
| `dev` | local, docker compose, CI | `POST /auth/dev-login` with a seed account's email. Signed with `AUTH_DEV_SECRET`, valid 8 hours. No password: demo data only |
| `entra-external-id` | cloud | Sign in with Microsoft Entra External ID (hosted email + password sign-up/sign-in) and send the **ID token**. The backend checks the tenant's signature, issuer and audience (`ENTRA_CLIENT_ID`) and needs an email claim |

- In `entra-external-id` mode a first-time user is created as a `patient`. Emails listed in the
  operator settings `CLINICIAN_EMAILS` / `ADMIN_EMAILS` get that role when they sign in. A token
  can never change anyone's role.
- `GET /queue/stream` also accepts the token as `?access_token=...`, because the browser's
  `EventSource` can't send headers. Only that endpoint should use it.

| Status | When | Body |
|---|---|---|
| 401 | No token, bad signature, expired, or unknown user | `{"detail": "Sign in required"}` / `{"detail": "Invalid or expired token"}` |
| 403 | Signed in, but the role isn't allowed | `{"detail": "Not allowed for your role"}` |

### `POST /auth/dev-login` (dev mode only)

Body `{"email": "patient1@example.com"}`. Returns
`{"access_token": "...", "token_type": "bearer", "user": {"id": 1, "email": "...", "role": "patient"}}`.
401 for an unknown account; 404 when `AUTH_MODE` isn't `dev`.

### `GET /me`

Returns `{"id": 1, "email": "patient1@example.com", "role": "patient"}`. In
`entra-external-id` mode this is also where a first-time user is created.

## Endpoints

### `GET /slots?date=2030-01-07&provider_id=1`

`date` is required, `provider_id` is optional. Returns `Slot[]`: free slots that start on that
UTC day and haven't started yet, earliest first. A slot whose only appointments are cancelled
counts as free.

| Status | When |
|---|---|
| 200 | Always, possibly `[]` |
| 422 | Missing or invalid `date`, or `provider_id` < 1 |

### `POST /appointments` (patient)

Body `{"slot_id": 1}`. The patient is the signed-in user (any `patient_id` in the body is
ignored). Returns the `Appointment`.

| Status | When | Body |
|---|---|---|
| 201 | Booked | `Appointment` |
| 404 | Unknown slot | `{"detail": "Slot not found"}` |
| 409 | Slot already booked, or already started | `{"detail": "Slot is already booked"}` / `{"detail": "Slot has already started"}` |
| 422 | Invalid body | validation error |

### `GET /appointments` (patient)

The signed-in patient's bookings that aren't cancelled, soonest first:

```json
[{"id": 7, "slot_id": 1, "status": "booked", "created_at": "2030-01-06T15:02:11Z",
  "starts_at": "2030-01-07T09:00:00Z", "provider_name": "Dr. Alex Example",
  "specialty": "General Practice", "intake_submitted": false}]
```

### `POST /intake` (patient)

Body `{"appointment_id": 7, "symptoms": "Chest pain since this morning"}`. `symptoms` is 1 to
4000 characters. The appointment service sends the text to the triage service, stores the result
and returns it. One intake per appointment.

| Status | When | Body |
|---|---|---|
| 201 | Triaged and stored | `TriageRecord` |
| 404 | Unknown appointment, or someone else's | `{"detail": "Appointment not found"}` |
| 409 | Appointment is cancelled, or already has an intake | `{"detail": "Appointment is cancelled"}` / `{"detail": "Intake already submitted"}` |
| 422 | Invalid body | validation error |

If the triage service is down or returns something invalid, the intake still succeeds with a
safe fallback: `urgency: "soon"` and a summary saying a clinician should review manually.

### `GET /queue` (clinician)

Returns `QueueEntry[]` for appointments that are `booked` or `checked_in`. Order: `urgent`, then
`soon`, then `routine`; within the same urgency, whoever submitted their intake first; patients
without an intake come last, by appointment time.

### `GET /queue/stream` (clinician)

[Server-Sent Events](https://developer.mozilla.org/docs/Web/API/Server-sent_events)
(`text/event-stream`). Use `new EventSource("/queue/stream?access_token=...")` in the browser.

- On connect, and again after **any** change to appointments or triage results, the server sends
  the whole queue: `event: queue` with `data:` set to the same JSON array as `GET /queue`.
- When nothing changes for 15 seconds it sends a comment line (`: keep-alive`), which
  `EventSource` ignores.
- Changes are delivered through Postgres `LISTEN/NOTIFY`, so this works with several replicas.

### `PATCH /triage/{id}` (clinician)

Body `{"final_urgency": "soon"}`. Sending the AI's own urgency means "accept"; anything else is an
override. Returns the updated `TriageRecord` with `reviewed_at` set. The database also
records which clinician decided (`reviewed_by`).

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
  "summary": "One paragraph for the clinician.",
  "tokens_used": 512,
  "fallback": false
}
```

`tokens_used` is reported by the Azure OpenAI client (`null` for the fake client). `fallback` is
`true` when the model failed or answered invalidly and the safe default (`soon`, "review
manually") was returned instead. The appointment service stores `tokens_used` with the result.

## Tables

See [schema.md](schema.md) for the full schema and the rules the database enforces.
