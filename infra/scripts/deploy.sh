#!/usr/bin/env bash
# Deploy from a laptop: the same steps as .github/workflows/deploy.yml, using your `az login`
# and the Terraform outputs directly. Use this when GitHub can't deploy with OIDC (our tenant
# blocks the federated credential).
#
#   bash infra/scripts/deploy.sh
#
# Needs: az (signed in), terraform (initialised in infra/terraform), docker, kubectl.
set -euo pipefail
export MSYS_NO_PATHCONV=1 # Git Bash on Windows: don't rewrite /subscriptions/... arguments

# On Git Bash, use a C:/... path: Windows programs (terraform.exe, docker.exe) need it
repo=$(cd "$(dirname "$0")/../.." && (pwd -W 2>/dev/null || pwd))
tf() { terraform -chdir="$repo/infra/terraform" "$@"; }
out() { tf output -json github_variables | python -c "import json,sys; print(json.load(sys.stdin)['$1'])"; }

ACR=$(out ACR_LOGIN_SERVER)
RG=$(out AZURE_RESOURCE_GROUP)
AKS=$(out AKS_NAME)
APP_HOST=$(out APP_HOST)
TAG=$(git -C "$repo" rev-parse --short HEAD)$(git -C "$repo" diff --quiet || echo "-dirty")
echo "Deploying $TAG to https://$APP_HOST"

echo "== Build and push images (arm64 for the AKS node, amd64 for everything else)"
PLATFORMS=linux/arm64,linux/amd64
az acr login --name "${ACR%%.*}"
for s in appointment-service triage-service; do
  docker buildx build --platform "$PLATFORMS" -t "$ACR/$s:$TAG" --push "$repo/services/$s"
done
docker buildx build --platform "$PLATFORMS" -t "$ACR/frontend:$TAG" --push \
  --build-arg VITE_AUTH_MODE="$(out FRONTEND_AUTH_MODE)" \
  --build-arg VITE_ENTRA_CLIENT_ID="$(out ENTRA_CLIENT_ID)" \
  --build-arg VITE_ENTRA_AUTHORITY="$(out ENTRA_AUTHORITY)" \
  "$repo/frontend"

work=$(cd "$(mktemp -d)" && (pwd -W 2>/dev/null || pwd)) # C:/... on Git Bash, for kubectl.exe
trap 'rm -rf "$work"' EXIT

echo "== Connect to AKS (credentials go to a temporary file, not your ~/.kube/config)"
export KUBECONFIG="$work/kubeconfig"
az aks get-credentials --resource-group "$RG" --name "$AKS" --file "$KUBECONFIG" --overwrite-existing

echo "== Install cert-manager"
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.16.2/cert-manager.yaml
kubectl -n cert-manager rollout status deploy/cert-manager-webhook --timeout=180s

echo "== Render the manifests with this deployment's values"
# Only the manifests and the SQL they reference, at the same relative paths
mkdir -p "$work/infra" "$work/services/appointment-service"
cp -r "$repo/infra/k8s" "$work/infra/"
cp -r "$repo/services/appointment-service/db" "$work/services/appointment-service/"
overlay="$work/infra/k8s/overlays/aks"
tf output -raw cloud_env > "$overlay/cloud.env"
sed -i "s|newName: REGISTRY/|newName: $ACR/|; s|newTag: latest|newTag: $TAG|" "$overlay/kustomization.yaml"
kubectl kustomize "$overlay" --load-restrictor=LoadRestrictionsNone > "$work/aks.yaml"

echo "== Apply, load the database schema, roll out"
kubectl -n clinic-portal delete job db-init --ignore-not-found
kubectl apply -f "$work/aks.yaml"
kubectl -n clinic-portal wait --for=condition=complete job/db-init --timeout=300s
kubectl -n clinic-portal logs job/db-init
kubectl -n clinic-portal rollout restart deploy/appointment-service deploy/triage-service deploy/frontend
for d in appointment-service triage-service frontend; do
  kubectl -n clinic-portal rollout status deploy/$d --timeout=300s
done

echo "== Smoke test (the first certificate can take a minute or two)"
curl -sf --retry 20 --retry-delay 15 --retry-all-errors "https://$APP_HOST/api/health"; echo
curl -sf "https://$APP_HOST/api/ready"; echo
echo "Done: https://$APP_HOST"
