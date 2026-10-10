# Clinic Appointment and AI Triage Portal

Cloud Computing semester project. Patients book appointments and describe symptoms in plain language. An AI service (Gemini on Vertex AI) turns the text into a structured triage result for the clinician, who can accept or override it. Clinic staff see a live queue dashboard.

> **Synthetic data only.** No real patient information is ever used. Security controls are "HIPAA-inspired", not a compliance claim. The AI is decision support, not diagnosis.

## Architecture (short version)

- **Azure:** Static Web Apps (frontend), AKS (containerized services), Key Vault (secrets)
- **Google Cloud:** Cloud SQL for PostgreSQL, Vertex AI (Gemini Flash), Cloud Storage, Identity Platform
- **Cross-cloud:** GitHub Actions (CI/CD with OIDC), Terraform (azurerm + google), Prometheus + Grafana

## Repo layout

```
services/appointment-service/   FastAPI: slots, booking, queue, SSE stream
services/triage-service/        FastAPI: PII redaction -> Gemini -> validated result
shared/                         code shared by services (auth, DB models, config)
frontend/                       React + Vite app
infra/terraform/                Terraform for Azure + GCP
infra/k8s/                      Kubernetes manifests
docs/                           API contract, architecture, AI-usage log
```

## Run locally (no cloud needed)

Prerequisites: Docker Desktop, Git, Python 3.12, Node 20+.

```bash
cp .env.example .env
docker compose up --build
```

- Appointment service: http://localhost:8001/health  (API docs: http://localhost:8001/docs)
- Triage service: http://localhost:8002/health  (API docs: http://localhost:8002/docs)
- Postgres: localhost:5432 (user/password/db from `.env`)

Run a service's tests without Docker:

```bash
cd services/appointment-service
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest
ruff check .
```

## Team workflow

1. Never push to `main`. Create a branch: `git checkout -b feat/short-description`
2. Make small commits and open a pull request early.
3. CI must pass and one teammate must approve before merging.
4. Never commit secrets. Use `.env` locally (it is git-ignored) and Key Vault in the cloud.
5. Add a line to `docs/ai-usage-log.md` whenever you use an AI tool for something meaningful.

## Team

| Member | Area |
|---|---|
| TBD | Backend (appointments, DB, auth), later Cloud/DevOps and Security |
| TBD | Backend (triage, AI, PII redaction, metrics) |
| TBD | Frontend |
