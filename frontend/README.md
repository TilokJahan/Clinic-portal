# Clinic portal frontend

React + TypeScript + Vite app for patients (book, send symptoms), clinicians (live triage queue,
accept or override the AI, review lab results), and lab techs (upload patient lab results from
CSV). Screens: [docs/wireframes](../docs/wireframes/README.md).

## Run it

Prerequisites: Node.js 20.19 or newer (CI uses Node 20, see `.nvmrc`).

```bash
npm install
npm run dev       # mock API, no backend needed
npm run dev:api   # real backend: proxies /api to http://localhost:8001
npm run build     # type-check and production build (what CI runs)
```

Open the URL Vite prints and pick a demo account. For `dev:api`, start the backend first
(`docker compose up` from the repo root). To point the proxy elsewhere, set
`API_PROXY_TARGET=http://host:port`.


The Lab Tech demo lets the user select a patient and upload a result file (including CSV, PDF, or
JPEG; 1 MB maximum). CSV result rows are parsed; other files are saved as browser-local attachments.
Uploads are visible to clinician accounts and shown to the matching patient account in the same
browser.

The patient home page includes a prototype message composer. Messages are saved in this browser and appear in the matching patient's clinician queue details in the same browser.

The additional lab-results screen and file uploads described above are browser-local prototypes.
The existing appointment-based lab upload and clinician review use the shared API separately.
The sign-in account list comes from `src/auth.ts`; it does not currently include a lab-tech demo
account. Lab-tech access requires an account assigned that role by the backend.

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
| `src/labResults.ts` | CSV parsing, patient matching, and browser-local storage for prototype lab uploads |
| `src/format.ts` | Local-time formatting, wait times; the API always sends UTC |

Every API call returns `{ ok: true, data }` or `{ ok: false, status, detail }` instead of
throwing, so pages can show the server's message (for example `409 Slot is already booked`).

AI output is always labelled "AI suggestion � clinician decides". It is decision support, not a
diagnosis.
