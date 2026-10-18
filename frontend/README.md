# Clinic portal frontend

React + TypeScript + Vite prototype for the patient booking/intake flow and clinician triage queue. The screens use a local mock API in `src/mockApi.ts`.

## Run locally

Prerequisites: Node.js 20.19+ (recommended by current Vite releases; this project uses Vite 6 and works with Node 20.12) and npm.

```bash
npm install
npm run dev
```

Open the local URL printed by Vite. Use the **Preview as** control to switch between clinician and patient views.

## Prototype screens

- Clinician overview and queue with urgency filters, patient search, intake summary, red flags, and review/override controls.
- Patient home, appointment time selection, and symptom intake form.
- Prototype sign-in at `/login` with patient/clinician role selection.
- Mock queue and appointment slots in `src/data.ts`; async API adapter in `src/mockApi.ts`.

The mock intake currently assigns routine urgency and general practice to new submissions. Replace the adapter with calls matching [`../docs/api.md`](../docs/api.md) when the backend is ready. AI output is presented as decision support and reviewed by a clinician; it is not a diagnosis.

```bash
npm run build
```
