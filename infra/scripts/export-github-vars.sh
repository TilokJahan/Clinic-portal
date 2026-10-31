#!/usr/bin/env bash
# Copy Terraform outputs into GitHub Actions variables for .github/workflows/deploy.yml.
# Run from the repo root after `terraform apply`, signed in with `gh auth login`.
# Nothing secret is copied: IDs and host names. The database password stays in Key Vault.
set -euo pipefail
cd "$(dirname "$0")/../terraform"

repo=$(terraform output -json github_variables >/dev/null && gh repo view --json nameWithOwner -q .nameWithOwner)
echo "Setting variables on $repo"

terraform output -json github_variables | jq -r 'to_entries[] | "\(.key)\t\(.value)"' |
  while IFS=$'\t' read -r name value; do
    gh variable set "$name" --repo "$repo" --body "$value"
  done

gh variable set CLOUD_ENV --repo "$repo" --body "$(terraform output -raw cloud_env)"

echo "Done. Start a deploy with: gh workflow run deploy.yml --repo $repo"
