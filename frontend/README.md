# Clinic portal frontend

React + TypeScript + Vite app for patients (book, send symptoms), clinicians (live triage queue,
accept or override the AI, review lab results), and lab techs (upload reports for scheduled
visits). Screens: [docs/wireframes](../docs/wireframes/README.md).

## Run it

Prerequisites: Node.js 20.19 or newer (CI uses Node 20, see `.nvmrc`).

```bash
npm install
npm run dev       # mock API, no backend needed
npm run dev:api   # real backend: proxies /api to http://localhost:8001
npm run build     # type-check and production build (what CI runs)
npm run test:lab  # lab API, file validation, role restrictions and approval regression tests
```

Open the URL Vite prints and pick a demo account. For `dev:api`, start the backend first
(`docker compose up` from the repo root). To point the proxy elsewhere, set
`API_PROXY_TARGET=http://host:port`.


The Lab Tech option signs in as `labtech1@example.com` through the same token-backed demo login
as other roles (a shared demo passcode is needed when required by the dev backend). In Entra
mode, the backend assigns the role. User IDs for real requests come from the sign-in response.

The lab workspace loads `GET /api/lab/worklist?date=YYYY-MM-DD`, showing booked and checked-in
visits for the chosen UTC day. It sends multipart `file` uploads to
`POST /api/lab/appointments/{appointment_id}/reports` with the current bearer token. Accepted
files are nonempty PDF, PNG and JPEG, up to 10 MiB; CSV is not supported by the backend.
The overview shows report status and refreshes while processing. Lab technicians cannot read
extracted results or approve explanations. Admins can also use the upload screen.

Clinicians review reports through the patient queue. Patients load reports for their own visits
and only see results after clinician approval. Lab files and results no longer use browser-local
storage. Existing browser-local prototype uploads are not sent to the backend automatically.

`npm run dev` uses the in-memory mock API with the same worklist and upload contract. Choose
the next weekday to see the seeded visits; mock uploads reset on reload. Use `npm run dev:api`
with the appointment service running to exercise persistent storage and real authentication.
API mode defaults to HTTP without needing an `.env.api` file; an explicit `VITE_API_MODE`
environment value overrides this default.

The patient home page includes a prototype message composer. Messages are saved in this browser and appear in the matching patient's clinician queue details in the same browser.

The Billing and statements page uses synthetic data from `src/billingApi.ts`. The mock defines the
backend contract as `GET /api/patients/{patient_id}/bills`, returning bill records with `id`,
`patient_id`, `description`, `service_date` (`YYYY-MM-DD`), `amount_cents`, `status` (`paid`,
`due`, or `overdue`), and nullable `due_date` (`YYYY-MM-DD`). Replace the mock implementation with
the backend call when that endpoint is available.

The whole stack, including this app on http://localhost:8080, also runs with
`docker compose up --build` from the repo root. In Docker, nginx serves the build and proxies
`/api` (including the Server-Sent Events stream) to the appointment service.

## How it is organised

| Path | What it does |
|---|---|
| `src/types.ts` | Types that mirror [docs/api.md](../docs/api.md) exactly (snake_case) |
| `src/api/index.ts` | Picks the API: `VITE_API_MODE=mock` (default) or `http`. The only switch |
| `src/api/http.ts` | Real calls with `fetch` and `EventSource` (`/queue/stream`) |
| `src/api/mock.ts` | In-memory API with the same shapes. The first Dr. Alex Example slot each day is "already taken" so the 409 message can be demoed |
| `src/pages/` | Login, patient home, booking, intake, clinician overview/queue, and lab results |
| `src/auth.ts` | Mock/dev demo sign-in, the dev passcode, and Microsoft Entra sign-in |
| `src/session.ts` | Shared token-backed session, sign-out, and expired-session handling |
| `src/labUpload.ts` | Shared file type, empty-file and 10 MiB validation for lab uploads |
| `src/format.ts` | Local-time formatting, wait times; the API always sends UTC |

Every API call returns `{ ok: true, data }` or `{ ok: false, status, detail }` instead of
throwing, so pages can show the server's message (for example `409 Slot is already booked`).

AI output is always labelled "AI suggestion � clinician decides". It is decision support, not a
diagnosis.
