# API Contract (v3, edit via pull request)

Every change to this file goes through a pull request that all three of us review (#10).

| Method | Path | Service | Role | Purpose | Status |
|---|---|---|---|---|---|
| GET | `/health` | all | none | Liveness check | done |
| POST | `/auth/dev-login` | appointment | none (dev only) | Demo token for a seed account | done |
| GET | `/me` | appointment | any | The signed-in user | done |
| GET | `/slots?date=YYYY-MM-DD&provider_id=` | appointment | any | List free slots | done |
| POST | `/assessments` | appointment | patient | Step 1 of booking: describe symptoms, get the priority and time limit | done |
| GET | `/slots/timeframes?priority=` | appointment | any | Each timeframe with its free times and whether the priority allows it | done |
| POST | `/appointments` | appointment | patient | Request a slot with an assessment (waits for approval) | done |
| POST | `/appointments/{id}/approve` | appointment | clinician | Approve a booking request | done |
| POST | `/appointments/{id}/decline` | appointment | clinician | Decline a request, with a note for the patient | done |
| GET | `/appointments` | appointment | patient | My bookings | done |
| GET | `/appointments/stream` | appointment | patient | Server-Sent Events: my bookings, live | done |
| POST | `/intake` | appointment | patient | Submit symptoms (calls triage-service) | done |
| GET | `/queue` | appointment | clinician | Waiting patients, most urgent first | done |
| GET | `/queue/stream` | appointment | clinician | Server-Sent Events for live updates | done |
| PATCH | `/triage/{id}` | appointment | clinician | Accept or override the AI result | done |
| POST | `/appointments/{id}/lab-reports` | appointment | patient | Upload a lab report (PDF/PNG/JPEG) | done |
| GET | `/lab/worklist?date=YYYY-MM-DD` | appointment | lab_tech / admin | Scheduled visits for the day, with report status | done |
| POST | `/lab/appointments/{id}/reports` | appointment | lab_tech / admin | Upload a lab report for any scheduled patient | done |
| GET | `/appointments/{id}/lab-reports` | appointment | patient (own) / clinician | Lab reports and results (not lab techs) | done |
| PATCH | `/lab-reports/{id}` | appointment | clinician | Approve (and edit) the patient explanation | done |
| POST | `/appointments/{id}/lab-requests` | appointment | clinician, physician | Ask the lab for a test, with an urgency | done |
| GET | `/lab/requests?status=open\|done` | appointment | lab_tech | The lab's requests, most urgent first | done |
| PATCH | `/lab/requests/{id}` | appointment | lab_tech | Mark a request scheduled or cancelled | done |
| GET | `/physician/schedule` | appointment | physician | The physician's own upcoming and recent visits | done |
| POST | `/appointments/{id}/complete` | appointment | physician | Complete a visit with a summary for the patient | done |
| GET | `/providers` | appointment | any | The doctors | done |
| GET, PATCH | `/admin/users`, `/admin/users/{id}` | appointment | admin | Users and roles; link a physician to a schedule | done |
| GET | `/appointments/{id}/earlier-slots` | appointment | clinician | Free earlier slots with any provider (max 10) | done |
| GET | `/appointments/{id}/alternative-slots` | appointment | clinician | Times that may be proposed: any doctor, within the priority (max 12) | done |
| POST | `/appointments/{id}/proposals` | appointment | clinician | Propose one to three times (replaces earlier proposals) | done |
| POST | `/appointments/{id}/reschedule-offers` | appointment | clinician | Offer the patient an earlier slot | done |
| POST | `/reschedule-offers/{id}/accept` | appointment | patient (own) | Accept: move to the earlier slot | done |
| POST | `/reschedule-offers/{id}/decline` | appointment | patient (own) | Decline: keep the booking | done |
| GET | `/lab-reports/{id}/file` | appointment | clinician | The original file | done |
| GET | `/urgency-matrix` | appointment | any signed-in user | How a priority is decided and how soon it is seen | done |
| GET | `/slots/earliest?within_hours=72` | appointment | any signed-in user | Free times in a timeframe, earliest first (max 12) | done |
| GET | `/slots/next-available?after_hours=72` | appointment | any signed-in user | First free time after a timeframe, or null | done |
| GET | `/appointments/{id}/schedule-options` | appointment | patient (own) | Times this visit can move to, within a timeframe | done |
| POST | `/appointments/{id}/reschedule` | appointment | patient (own) | Accept a new time; intake and labs move with it | done |
| POST | `/triage` | triage | internal | Redact PII, call AI, return structured result | done |
| POST | `/labs/interpret` | triage | internal | OCR + unit conversion + rule flags + AI summary | done |

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
 "starts_at": "2030-01-07T09:00:00Z", "ends_at": "2030-01-07T09:30:00Z", "reserved": false}
```

`reserved` is `true` for a slot in the urgent reserve that ordinary patients can't book right now. Only urgent patients
(schedule options) and clinicians (earlier slots) are ever shown one; see
[triage.md](triage.md#urgent-reserve).

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
  "triage": { "...": "TriageRecord, or null before the patient submits an intake" },
  "needs_earlier_visit": false,
  "offer_pending": false
}
```

- `needs_earlier_visit` is `true` when the visit is `booked` and later than its urgency allows
  (`urgent`: more than 24 hours away, `soon`: more than 3 days), and no earlier visit has been
  offered yet. It's the cue to offer one or call the patient, for example when nothing was free in
  time.
- `offer_pending` is `true` while an offered earlier visit waits for the patient's answer.

## Authentication

The backend's `AUTH_MODE` picks how tokens are issued; the endpoints work the same either way.

| Mode | Where | How you get a token |
|---|---|---|
| `dev` | local, docker compose, CI, the live demo | `POST /auth/dev-login` with a seed account's email (and the shared `passcode` when `DEMO_PASSCODE` is set, as on the live demo). Signed with `AUTH_DEV_SECRET`, valid 8 hours. No per-user password: demo data only |
| `entra-external-id` | cloud | Sign in with Microsoft Entra External ID (hosted email + password sign-up/sign-in) and send the **ID token**. The backend checks the tenant's signature, issuer and audience (`ENTRA_CLIENT_ID`) and needs an email claim |

- In `entra-external-id` mode a first-time user is created as a `patient`. Emails listed in the
  operator settings `CLINICIAN_EMAILS` / `PHYSICIAN_EMAILS` / `LAB_TECH_EMAILS` / `ADMIN_EMAILS` get that role when they
  sign in (an email on several lists gets the most privileged role). A token
  can never change anyone's role.
- `GET /queue/stream` and `GET /appointments/stream` also accept the token as
  `?access_token=...`, because the browser's `EventSource` can't send headers. Only those
  endpoints should use it.

| Status | When | Body |
|---|---|---|
| 401 | No token, bad signature, expired, or unknown user | `{"detail": "Sign in required"}` / `{"detail": "Invalid or expired token"}` |
| 403 | Signed in, but the role isn't allowed | `{"detail": "Not allowed for your role"}` |

### `POST /auth/dev-login` (dev mode only)

Body `{"email": "patient1@example.com", "passcode": "..."}`. `passcode` is optional unless the
operator set `DEMO_PASSCODE` (the live demo does; local runs and CI don't). Returns
`{"access_token": "...", "token_type": "bearer", "user": {"id": 1, "email": "...", "role": "patient"}}`.
401 `Wrong or missing demo passcode` when a passcode is required and doesn't match (checked before
the account lookup, so it doesn't reveal which emails exist); 401 for an unknown account; 404 when
`AUTH_MODE` isn't `dev`.

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

Body `{"slot_id": 1, "assessment_id": 12}`. The patient is the signed-in user (any
`patient_id` in the body is ignored). Returns the `Appointment`, with `"approved_at": null`.

**Booking is three steps, symptoms first:**

1. `POST /assessments` with `{"symptoms": "..."}` (1–4000 characters) runs the same triage as
   `POST /intake` and returns `{"triage": TriageRecord, "max_within_hours": 24}`. The triage
   belongs to the patient (`appointment_id` is `null`) until a time is requested with it; the
   symptom text is never stored. Nothing reaches the clinician queue yet.
2. The patient chooses a time. `GET /slots/timeframes?priority=urgent` lists each timeframe as
   `{"hours", "label", "free", "allowed"}`: the app greys out a timeframe with `free: 0` or
   `allowed: false`. `GET /slots?date=...&include_booked=true` lists the whole day with
   `"available": false` on booked times (and on the urgent reserve unless `urgent=true`).
   `GET /slots/earliest` and `/slots/next-available` take `urgent=true` too.
3. `POST /appointments` with the `assessment_id`. The time must start within
   `max_within_hours`, unless nothing at all is free that soon (then a later time is allowed and
   the queue flags it): otherwise 422 with how soon the patient needs to be seen. Only an urgent
   assessment may take the urgent reserve. The assessment is linked to the new appointment and
   can't be used again (404); one older than a day answers 409 `"Please describe your symptoms
   again"`.

`{"slot_id": 1, "symptoms": "..."}` (assessed with the request) and `{"slot_id": 1}` (symptoms
later via `POST /intake`) still work for older clients.

This is a **request**: the slot is held at once, and the visit waits for a clinician to approve
it (`approved_at` is set) or decline it. `symptoms` (1–4000 characters) are sent to the triage
service first, exactly like `POST /intake`, so the clinician sees the urgency with the request;
the text is never stored. The web app always sends them. Without `symptoms` the request waits
for `POST /intake`, and can't be approved until then.

| Status | When | Body |
|---|---|---|
| 201 | Requested | `Appointment` |
| 404 | Unknown slot | `{"detail": "Slot not found"}` |
| 409 | Slot already booked, or already started | `{"detail": "Slot is already booked"}` / `{"detail": "Slot has already started"}` |
| 422 | Invalid body | validation error |

### `GET /appointments` (patient)

The signed-in patient's bookings, soonest first. Cancelled ones are left out, except a request
a clinician declined whose time hasn't come yet (so the patient sees why):

```json
[{"id": 7, "slot_id": 1, "status": "booked", "created_at": "2030-01-06T15:02:11Z",
  "starts_at": "2030-01-07T09:00:00Z", "provider_name": "Dr. Alex Example",
  "specialty": "General Practice", "intake_submitted": false, "approved": false,
  "declined": false, "decline_reason": null, "pending_offer": null}]
```

`approved` is `false` while the request waits for a clinician. A declined request has
`"status": "cancelled"`, `"declined": true` and the clinician's note in `decline_reason` (or
`null`).

### `POST /appointments/{id}/approve` and `/decline` (clinician)

A clinician decides a request from the queue, where it has `"awaiting_approval": true`.

- **approve** sets `approved_at`. It needs the patient's symptoms first: 409 `"The patient hasn't
  described their symptoms yet"`.
- **decline** takes `{"reason": "..."}` (optional, at most 500 characters, shown to the patient).
  The appointment is cancelled, so the slot opens again, and any offered time expires.
- Both answer 404 for an unknown appointment, 409 `"Already approved"` or `"This request is no
  longer open"`, and 403 for any role but clinician or admin.
- Instead, the clinician can propose other times (below). If the patient accepts one, the new
  visit is approved. A visit the patient moves themselves (`POST /appointments/{id}/reschedule`)
  is a new request and needs approval again.

### Proposing other times (clinician) and answering them (patient)

- `GET /appointments/{id}/alternative-slots`: free, upcoming times with **any** doctor that fit
  the patient's priority (or are at least earlier than the current visit), soonest first, at
  most 12. Includes the urgent reserve.
- `POST /appointments/{id}/proposals` with `{"slot_ids": [4, 9]}` (one to three, different):
  returns the `RescheduleOffer[]`. New proposals replace any still open. 422 for a time later
  than the priority allows, 409 for a booked or started one.
  (`POST /appointments/{id}/reschedule-offers` with `{"slot_id": 4}` is the single-time form.)
- The patient sees them in `pending_offers` on `GET /appointments` and then either:
  - accepts one: `POST /reschedule-offers/{id}/accept` (the others expire; the visit moves and
    is approved);
  - chooses another time themselves: `POST /appointments/{id}/reschedule` (the proposals
    expire; the new time needs approval again); or
  - says none of them work: `POST /reschedule-offers/{id}/decline` with an optional
    `{"note": "Afternoons only"}` (at most 500 characters). All open proposals are declined and
    the queue entry shows `offer_declined_note` (the note, or `""`) until new times are
    proposed.

`pending_offer` is `null`, or an earlier visit the care team has offered:
`{"id": 4, "slot_id": 12, "starts_at": "2030-01-06T10:00:00Z", "provider_name": "Dr. Alex Example"}`.
It has no clinical detail, and offers whose slot was taken or has started are not shown.

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

Returns `QueueEntry[]` for appointments that are `checked_in`, or `booked` and started less than
12 hours ago (an older booked visit was missed, and the patient's page lists it as past). Order: `urgent`, then
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

### `GET /appointments/stream` (patient)

Server-Sent Events for the signed-in patient's own bookings, so their home page updates the
moment a clinician offers an earlier visit or a booking moves.

- On connect it sends `event: appointments` with `data:` set to the same JSON array as
  `GET /appointments`, and again whenever that list changes.
- It listens on the same NOTIFY channel as `/queue/stream`, but only sends when this patient's
  list actually differs, so other patients' changes never reach them. Otherwise it sends
  `: keep-alive` every 15 seconds.
- 401 without a token, 403 for any role but patient.

### `PATCH /triage/{id}` (clinician)

Body `{"final_urgency": "soon"}`. Sending the AI's own urgency means "accept"; anything else is an
override. Returns the updated `TriageRecord` with `reviewed_at` set. The database also
records which clinician decided (`reviewed_by`).

| Status | When |
|---|---|
| 200 | Saved |
| 404 | Unknown triage id (`{"detail": "Triage result not found"}`) |
| 422 | `final_urgency` isn't `routine`, `soon` or `urgent` |

### Earlier-visit offers

When a lab result makes a patient urgent but their visit is days away, a clinician can offer an
earlier slot. Nothing moves until the patient accepts.

**`GET /appointments/{id}/earlier-slots`** (clinician): free, upcoming slots with any provider
that start before this visit, earliest first (the patient's own provider first at the same time),
at most 10 (`Slot[]`). Empty when the visit is already at the earliest free time. 404 for an unknown
appointment, 409 if it isn't `booked`.

**`POST /appointments/{id}/reschedule-offers`** (clinician), body
`{"slot_id": 12, "reason": "optional note for the care team"}`. Returns **201** with
`{id, appointment_id, proposed_slot_id, provider_name, starts_at, status: "pending", reason,
created_at}`. The `reason` is never shown to the patient.

| Status | When |
|---|---|
| 404 | Unknown appointment or slot |
| 409 | Appointment isn't booked; the slot has started or is already booked; an offer is already pending |
| 422 | The slot isn't earlier than the current visit |

**`POST /reschedule-offers/{id}/accept`** (patient, own offers only). In one transaction the
patient is booked into the new slot, the intake and lab reports move to the new appointment (so
they stay in the queue), and the old appointment is cancelled. Returns the new `MyAppointment`.

**`POST /reschedule-offers/{id}/decline`** (patient, own offers only). The booking stays as it is.
Returns `{"id": 4, "status": "declined"}`.

| Status | When |
|---|---|
| 404 | Unknown offer, or one that belongs to another patient |
| 409 | Already answered; or (accept) the slot was just taken or has started, or the original visit was cancelled. A lapsed offer is marked `expired` and can't be used again |

When two patients accept offers for the same slot, the database's unique index on active slots
lets one through; the other gets 409.

### Urgency matrix and choosing a time

The matrix is in `app/urgency.py` and explained in [triage.md](triage.md#urgency-matrix). Each
priority has a longest timeframe: `urgent` 24 hours, `soon` 72, `routine` 336 (2 weeks); before an
intake there is no priority and any timeframe is allowed. Timeframes are 24, 72, 168 and 336 hours.

**`GET /urgency-matrix`** (any signed-in user):
`{"levels": [{urgency, seen_within_hours, seen_within, symptom_signals[], lab_signals[], action}],
"rules": [...], "timeframes": [{"hours": 24, "label": "Within 24 hours"}, ...]}`.

**`GET /slots/earliest?within_hours=72&provider_id=1`** (any signed-in user): free, upcoming
`Slot[]` that start in the next `within_hours`, earliest first, at most 12. Used to book by
timeframe: the frontend proposes the first one and the patient accepts it or picks another. 422 if
`within_hours` isn't one of the timeframes. The urgent reserve is only listed on its own day while
no urgent patient is waiting.

**`GET /slots/next-available?after_hours=72&provider_id=1`** (any signed-in user): the first free
`Slot` after the timeframe, however far away, or `null` if there is none. Shown when nothing is
free inside the timeframe, so booking is never a dead end.

**`GET /appointments/{id}/schedule-options?within_hours=72`** (patient, own booked visit):

```json
{"appointment_id": 7, "starts_at": "2030-01-14T09:00:00Z", "priority": "routine",
 "max_within_hours": 24, "care_team_limit": true, "within_hours": 24, "current_fits": false,
 "slots": ["...Slot, earliest first, at most 12"]}
```

- `priority` is the symptom priority the patient already saw after their intake (or `null`).
- `max_within_hours` comes from the same priority the queue uses (symptoms and labs combined,
  `EFFECTIVE_URGENCY`). When that is stricter than `priority`, for example after a critical lab
  value the patient hasn't been shown yet, `care_team_limit` is `true` and the screen only says
  the care team would like to see them sooner. No lab detail is sent.
- Without `within_hours`, the longest allowed timeframe is used. A longer one is a 422 with
  `"Your care team needs to see you within 24 hours. Please choose an earlier time."`
- `current_fits` is `true` when the current visit already falls inside the timeframe.
- `next_available` is set only when `slots` is empty: the first free time after the timeframe,
  or `null` if there is none at all.
- Urgent patients also see the urgent reserve (`"reserved": true`); others never do.

**`POST /appointments/{id}/reschedule`** (patient, own), body `{"slot_id": 12}`. In one
transaction (the same one that accepts an offer) the patient is booked into the new slot, the
intake and lab reports move to the new appointment, open offers for the old one expire, and the
old appointment is cancelled. Returns the new `MyAppointment`.

| Status | When |
|---|---|
| 404 | Unknown appointment (or someone else's), or unknown slot |
| 409 | The visit isn't `booked`; the slot has started or is already booked (including your own); the slot is in the urgent reserve and the patient isn't urgent |
| 422 | The slot is later than the priority allows **and** not earlier than the current visit. A time past the limit that is still sooner than the current visit is accepted: when nothing is free in time, coming sooner is safer |

`POST /appointments` also answers 409 `"That time is kept free for urgent care. Please pick
another."` for a slot in the urgent reserve that isn't open to ordinary booking.

### Lab reports

See [labs.md](labs.md) for the pipeline and rules.

**`POST /appointments/{id}/lab-reports`** (patient, own appointment): `multipart/form-data` with a
`file` field: PDF, PNG or JPEG, up to 10 MB. Returns **202** with the `LabReport` in status
`processing`; it's read in the background and the queue updates live when it's done.

| Status | When |
|---|---|
| 202 | Stored, being read |
| 404 | Unknown appointment, or someone else's |
| 409 | Appointment is cancelled |
| 413 | Over 10 MB |
| 415 | Not a PDF, PNG or JPEG |
| 422 | Empty file |

**`LabReport`**

```json
{
  "id": 4, "appointment_id": 7, "content_type": "application/pdf",
  "status": "ready",
  "uploaded_at": "2030-01-06T15:10:00Z", "processed_at": "2030-01-06T15:10:06Z",
  "lab_urgency": "urgent",
  "reason": "Critical: potassium 6.8 mmol/L",
  "clinician_summary": "Potassium critically high at 6.8 mmol/L ...",
  "patient_explanation": "Your potassium was higher than the usual range ...",
  "explanation_approved": false, "explanation_approved_at": null,
  "extraction_confidence": 0.97,
  "results": [
    {"display_name": "Potassium", "test_name": "Potassium", "canonical": "potassium",
     "value": 6.8, "unit": "mmol/L", "ref_low": 3.5, "ref_high": 5.1,
     "flag": "critical_high", "confidence": 0.98,
     "needs_verification": false, "verification_reason": null}
  ]
}
```

- `status`: `processing`, `ready`, `needs_review` (a value needs checking, or nothing could be
  read) or `failed`.
- `flag`: `normal`, `low`, `high`, `critical_low`, `critical_high` or `unknown`, from fixed rules.
- Values are in the canonical unit when the test is recognized (e.g. glucose in mg/dL).

**`GET /lab/worklist?date=YYYY-MM-DD`** (lab technician or admin): booked and checked-in
appointments that start on the day (UTC, default today), earliest first. It has what a technician
needs and nothing clinical: no symptoms, triage results, AI summaries, names or emails.

```json
[{"appointment_id": 7, "patient_label": "Patient 0007", "starts_at": "2030-01-07T09:00:00Z",
  "provider_name": "Dr. Alex Example", "status": "booked",
  "reports": [{"id": 3, "status": "ready", "uploaded_at": "2030-01-07T08:12:00Z",
               "lab_urgency": "urgent", "reason": "Critical: potassium 6.8 mmol/L"}]}]
```

**`POST /lab/appointments/{id}/reports`** (lab technician or admin): same `file` field and limits
as the patient upload, for any patient's appointment. Returns **202** with the `LabReport` in
status `processing` (the response never contains results). The uploader's id is saved in
`lab_reports.uploaded_by`, and `lab_uploads_total` is labelled by `role`.

| Status | When |
|---|---|
| 202 | Stored, being read |
| 403 | Not a lab technician or admin |
| 404 | Unknown appointment |
| 409 | Appointment is cancelled or completed |
| 413 / 415 / 422 | Over 10 MB / not a PDF, PNG or JPEG / empty file |

**`GET /appointments/{id}/lab-reports`**: newest first. Lab technicians get **403** (they upload,
they don't read). Clinicians get everything. Patients get
only `id`, `status`, dates and `explanation_approved` until a clinician approves; after that also
`patient_explanation` and `results` (never `reason` or `clinician_summary`).

**`PATCH /lab-reports/{id}`** (clinician): body `{"patient_explanation": "..."}` (1–3000
characters). Saves the text and approves it for the patient. 404 if the report is unknown or not
read yet (`processing` / `failed`).

**`GET /lab-reports/{id}/file`** (clinician): the original file, `Cache-Control: no-store`.

**Queue entries** also carry `lab` (the latest report: `report_id`, `status`, `urgency`,
`reason`, `explanation_approved`) and `urgency`: the higher of the symptom urgency and the lab
urgency, unless a clinician decided after the lab came in.

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


## Roles, kinds of tests and lab requests (schema v9)

**Roles.** `patient`, `clinician` (triage and booking approval: the live queue), `physician`
(a doctor, linked by an admin to one provider's schedule), `lab_tech` and `admin` (every staff
page, plus users and roles). Clinical data (symptoms, triage, lab results) is readable by
clinicians, physicians and admins; lab technicians see only labels, times and test requests.

**Kinds of tests.** Lab reports have an `exam_type`: `blood`, `urine`, `ultrasound`, `xray`,
`ct`, `mri`, `ecg` or `other`, and an optional `taken_on` date. Uploads take both as form
fields (`exam_type`, `taken_on`; the lab's upload also takes `request_id`). Blood and urine
reports go through OCR and the rules; imaging and ECG reports are stored as `needs_review` for a
clinician or physician to read and explain.

**Suggested tests.** Fixed keyword rules (`app/lab_needs.py`) read the symptoms at assessment or
intake and store `suggested_tests` on the triage result; the text itself is never stored. The
booking page then asks for a recent result (the last 40 days). Queue entries and the patient's
appointments carry `lab_needs`: for each suggested test, `recent`, `outdated` (only older than
40 days), `missing` or `requested`.

**Lab requests.** `POST /appointments/{id}/lab-requests` with `{"exam_type": "ultrasound",
"urgency": "urgent", "note": "For the lab"}` (one open request per kind of test, 409 otherwise).
The lab sees `GET /lab/requests` most urgent first, can mark one `scheduled` or `cancelled`, and
completes it by uploading the result with `request_id`. Patients see their requests without the
note.

**Physicians.** `GET /physician/schedule` lists the linked provider's visits from today on, then
those completed in the last 14 days (`QueueEntry`). `POST /appointments/{id}/complete` with
`{"summary": "..."}` needs an approved booking on their schedule; the patient sees
`visit_summary` and `completed_at` on `GET /appointments`.


## Lab visits and admin invitations (schema v10, file `schemav9z_lab_visits.sql`)

**Lab visits.** After a test is requested, the lab technician proposes lab times; the lab is
open weekdays 8:00–16:00 (clinic time), one patient every 15 minutes.

| Method | Path | Who | What |
|---|---|---|---|
| GET | `/lab/requests/{id}/times` | lab_tech | Free lab times within the urgency's window (urgent 24 h, soon 3 days, routine 2 weeks); `{"within_hours", "in_time", "times"}`. If nothing is free in time, the first free times after (`in_time: false`) |
| POST | `/lab/requests/{id}/propose` | lab_tech | `{"times": [...]}`, one to three: status becomes `proposed` |
| GET | `/lab-requests/{id}/times` | patient (own) | Free lab times they may choose |
| POST | `/lab-requests/{id}/schedule` | patient (own) | `{"starts_at": "..."}`: one of the proposed times or another free time that fits; status `scheduled`. Can be moved again the same way. 409 if taken (a unique index allows one patient per lab time) |
| GET | `/lab/requests` | lab_tech, clinician, physician, admin | The lab list; clinical staff follow it read-only |

Lab requests now carry `proposed_times` and `scheduled_at`; statuses are `requested`,
`proposed`, `scheduled`, `completed`, `cancelled`.

**Invitations.** The admin invites someone by email with a role; the portal makes a personal
link (`/invite/<token>`, 7 days, works once) that the admin sends from their own email (the app
has no email service: "Email it" opens a draft in the admin's email app).

| Method | Path | Who | What |
|---|---|---|---|
| POST | `/admin/invitations` | admin | `{"email", "role", "provider_id"}` (a physician needs a schedule). Replaces an older pending invitation for the same email. Returns the invitation with its `link` |
| GET | `/admin/invitations` | admin | The last 100, newest first, with `status`: pending, accepted, expired, revoked |
| POST | `/admin/invitations/{id}/revoke` | admin | Withdraw a pending one |
| GET | `/invitations/{token}` | anyone with the link | Who it's for and as what, and `method`: `accept` (demo) or `sign_up` (Entra) |
| POST | `/invitations/{token}/accept` | anyone with the link | Demo sign-in only: creates the account with the role and returns a token like `/auth/dev-login`. With Entra External ID, signing up with the invited email applies the invitation at the first sign-in |

**Account control.** `PATCH /admin/users/{id}` also takes `"active": false|true`. Roles and the
active flag are read from the database on every request, so a role change applies at once and a
disabled account gets 403 `"This account is disabled"` (the app then signs it out). Admins can't
change or disable their own account.
