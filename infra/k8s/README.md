# Kubernetes manifests

Kustomize, one base and two overlays.

| Folder | What it is |
|---|---|
| `base/` | Appointment and triage services: Deployments, Services, probes, config, HPA, PDB, NetworkPolicy |
| `overlays/local/` | A laptop cluster (kind): adds Postgres (seeded from `db/schema.sql` + `db/seed.sql`) and the frontend; dev sign-in, fake AI client |
| `overlays/aks/` | Azure Kubernetes Service (applied by `.github/workflows/deploy.yml`): images from ACR, secrets from Key Vault, Cloud SQL + Vertex AI through keyless Workload Identity Federation, HTTPS ingress |

## What the base gives every pod

- **Hardened:** non-root user, read-only root filesystem, no Linux capabilities, no privilege
  escalation, `RuntimeDefault` seccomp profile, CPU/memory requests and memory limits.
- **Probes:** the appointment service is only *ready* when the database answers (`/ready`);
  the triage service gets a startup probe because the spaCy model takes a while to load.
- **Scaling:** the appointment service runs 2–5 replicas (HPA on CPU) with a PodDisruptionBudget,
  so node upgrades never take the API down. Live queue updates work across replicas because they
  go through Postgres `LISTEN/NOTIFY`.
- **Network:** a NetworkPolicy lets only the appointment service (and metrics scrapers in
  `kube-system`) reach the triage service. It is never exposed outside the cluster.
- **Metrics:** `prometheus.io/scrape` annotations; `/metrics` is never routed by the ingress.

## Run it locally on kind

Needs Docker and [kind](https://kind.sigs.k8s.io/).

```bash
kind create cluster --name clinic
docker compose build
for s in appointment-service triage-service frontend; do docker tag clinic-portal-$s clinic/$s:local; done
kind load docker-image clinic/appointment-service:local clinic/triage-service:local clinic/frontend:local --name clinic
kubectl kustomize infra/k8s/overlays/local --load-restrictor=LoadRestrictionsNone | kubectl apply -f -
kubectl -n clinic-portal port-forward svc/frontend 8080:80
```

Open http://localhost:8080. Clean up with `kind delete cluster --name clinic`.

CI does the same on every pull request (the `kubernetes` job) and validates both overlays with
kubeconform.

## How the AKS overlay connects to everything

```
Browser (Static Web App) --HTTPS--> ingress (clinic-nginx, Let's Encrypt cert)
    --> appointment-service --> Cloud SQL Auth Proxy (sidecar) --> Cloud SQL (Google)
                            --> triage-service --> Vertex AI Gemini (Google)
Secrets: Azure Key Vault --(Secrets Store CSI, workload identity)--> clinic-secrets
Google credentials: pod's Kubernetes token --(Workload Identity Federation)--> GCP service account
```

- **No keys anywhere.** Azure access (Key Vault) uses AKS workload identity; Google access
  (Cloud SQL proxy, Vertex AI) exchanges the pod's Kubernetes token for short-lived Google
  credentials. `credential-config.json` only describes that exchange; it isn't secret.
- **Database schema:** the `db-init` Job loads `db/schema.sql` and the synthetic seed into
  Cloud SQL the first time (it skips when the tables exist).
- **Per-deployment values** (registry, project, Key Vault name, identities, host name) are in
  `overlays/aks/cloud.env` and `credential-config.json`. The deploy workflow overwrites both from
  `terraform output` before applying, so the committed files keep placeholders.
- **HTTPS:** the AKS application routing add-on runs a dedicated nginx controller with an Azure
  DNS label (`<DNS_LABEL>.<region>.cloudapp.azure.com`); cert-manager gets the certificate.
  The ingress turns off buffering for the Server-Sent Events stream.
