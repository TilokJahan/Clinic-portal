# Clinic Appointment and AI Triage Portal

Cloud Computing semester project. Patients book appointments and describe symptoms in plain language. An AI service (Azure OpenAI) turns the text into a structured triage result for the clinician, who can accept or override it. Clinic staff see a live queue dashboard.

> **Synthetic data only.** No real patient information is ever used. Security controls are "HIPAA-inspired", not a compliance claim. The AI is decision support, not diagnosis.

## Architecture (short version)

Everything runs on **Microsoft Azure** (Canada Central):

- **Compute:** AKS (frontend + both services), Container Registry
- **Data and AI:** Azure Database for PostgreSQL Flexible Server (private network only), Azure OpenAI (`gpt-4o-mini`, keyless)
- **Identity and secrets:** Microsoft Entra External ID (patient sign-up/sign-in), Key Vault, workload identity
- **Delivery and operations:** GitHub Actions (CI/CD with OIDC), Terraform (azurerm), Azure Storage (Terraform state), Prometheus + Grafana

> We first planned Google Cloud for the database, AI and sign-in, but moved everything to Azure
> when the Google account couldn't be used. The AI client, prompt and safety fallback are the
> same; only the provider changed.

Diagram and deployment steps: [infra/README.md](infra/README.md).

## Documentation

| Topic | File |
|---|---|
| API contract (every endpoint, auth, errors) | [docs/api.md](docs/api.md) |
| Database schema | [docs/schema.md](docs/schema.md) |
| Triage: redaction, AI prompt, evaluation | [docs/triage.md](docs/triage.md) |
| Security and privacy controls | [docs/security.md](docs/security.md) |
| Monitoring (metrics, Grafana) | [docs/monitoring.md](docs/monitoring.md) |
| Infrastructure and deployment | [infra/README.md](infra/README.md), [infra/k8s/README.md](infra/k8s/README.md) |
| Cloud accounts and budgets | [docs/cloud-accounts.md](docs/cloud-accounts.md) |
| Screens | [docs/wireframes](docs/wireframes/README.md) |
| AI-usage log | [docs/ai-usage-log.md](docs/ai-usage-log.md) |

## Repo layout

```
services/appointment-service/   FastAPI: auth, slots, booking, intake, queue + SSE stream, review
services/triage-service/        FastAPI: PII redaction -> Azure OpenAI -> validated result
frontend/                       React + Vite app (patient and clinician screens)
infra/terraform/                Terraform for Azure
infra/k8s/                      Kubernetes manifests (kind for local, AKS for the cloud)
infra/monitoring/               Prometheus + Grafana for docker compose
docs/                           API contract, schema, security, monitoring, AI-usage log
shared/                         reserved for code shared by services (empty so far)
```

## Run locally (no cloud needed)

Prerequisites: Docker Desktop, Git, Python 3.12, Node 20+.

```bash
cp .env.example .env
docker compose up --build
```

- **App: http://localhost:8080** — pick a demo patient or clinician (synthetic accounts)
- Appointment service: http://localhost:8001/health  (API docs: http://localhost:8001/docs)
- Triage service: http://localhost:8002/health  (API docs: http://localhost:8002/docs)
- Postgres: localhost:5432 (user/password/db from `.env`)

Add monitoring with `docker compose --profile monitoring up --build` (Grafana on
http://localhost:3000, Prometheus on http://localhost:9090). To try the Kubernetes manifests on
your laptop, see [infra/k8s/README.md](infra/k8s/README.md). After changing `db/schema.sql`,
reset the database with `docker compose down -v`.

The frontend alone, without any backend: `cd frontend && npm install && npm run dev` (mock API).

Run a service's tests without Docker:

```bash
cd services/appointment-service
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
# Database tests need Postgres, e.g. `docker compose up -d db`, then:
export TEST_DATABASE_URL=postgresql://clinic:local_dev_password_change_me@localhost:5432/clinic
pytest            # without TEST_DATABASE_URL the database tests are skipped
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
| Tabarek (@Tabarek92) | Backend (appointments, DB, auth), Cloud/DevOps and Security |
| Tilok Jahan (@TilokJahan) | Backend (triage, AI, PII redaction, metrics) |
| Ruth Bahre (@ruthbah) | Frontend |
