# Kubernetes manifests

Kustomize, one base and two overlays.

| Folder | What it is |
|---|---|
| `base/` | Frontend, appointment and triage services: Deployments, Services, probes, config, HPA, PDB, NetworkPolicy |
| `overlays/local/` | A laptop cluster (kind): adds Postgres (seeded from `db/schema.sql` + `db/seed.sql`); dev sign-in, fake AI client |
| `overlays/aks/` | Azure Kubernetes Service (applied by `.github/workflows/deploy.yml`): images from ACR, secrets from Key Vault, PostgreSQL Flexible Server, Azure OpenAI through workload identity, Entra External ID sign-in, HTTPS ingress |

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
kubectl -n clinic-portal port-forward svc/frontend 8080:80   # Service port 80 -> nginx 8080
```

Open http://localhost:8080. Clean up with `kind delete cluster --name clinic`.

CI does the same on every pull request (the `kubernetes` job) and validates both overlays with
kubeconform.

## How the AKS overlay connects to everything

```
Browser --HTTPS--> ingress (clinic-nginx, Let's Encrypt) --> frontend (nginx)
    /api --> appointment-service --> PostgreSQL Flexible Server (private subnet, TLS)
                                 --> triage-service --> Azure OpenAI (Entra token, no key)
Secrets: Azure Key Vault --(Secrets Store CSI, workload identity)--> clinic-secrets
Sign-in: Microsoft Entra External ID --(ID token)--> appointment-service verifies it
```

- **No keys anywhere.** Both services use AKS workload identity: the appointment service for Key
  Vault, the triage service for Azure OpenAI.
- **One origin.** The ingress sends everything to the frontend, whose nginx proxies `/api` to the
  appointment service, so the browser never makes cross-origin calls. Buffering is off for the
  Server-Sent Events stream; `/api/metrics` returns 404.
- **Database schema:** the `db-init` Job loads `db/schema.sql` and the synthetic seed into the
  PostgreSQL server the first time (it skips when the tables exist).
- **Per-deployment values** (registry, Key Vault name, identities, OpenAI endpoint, sign-in
  tenant, host name) are in `overlays/aks/cloud.env`. The deploy workflow overwrites it from
  `terraform output` before applying, so the committed file keeps placeholders.
- **HTTPS:** the AKS application routing add-on runs a dedicated nginx controller with an Azure
  DNS label (`<DNS_LABEL>.<region>.cloudapp.azure.com`); cert-manager gets the certificate.
