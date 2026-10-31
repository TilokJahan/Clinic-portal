# Clinic portal frontend

React + TypeScript + Vite app for patients (book, send symptoms) and clinicians (live triage
queue, accept or override the AI). Screens: [docs/wireframes](../docs/wireframes/README.md).

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
| `src/pages/` | Login, patient home, booking, intake, clinician overview and queue |
| `src/session.ts` | Prototype sign-in with synthetic demo accounts (replaced by JWT auth later) |
| `src/format.ts` | Local-time formatting, wait times; the API always sends UTC |

Every API call returns `{ ok: true, data }` or `{ ok: false, status, detail }` instead of
throwing, so pages can show the server's message (for example `409 Slot is already booked`).

AI output is always labelled "AI suggestion · clinician decides". It is decision support, not a
diagnosis.
