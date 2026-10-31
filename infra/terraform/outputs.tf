# Everything the deploy workflow needs. infra/scripts/export-github-vars.sh copies these into
# GitHub Actions variables, so the workflow never needs access to Terraform state.

output "cloud_env" {
  description = "Contents for infra/k8s/overlays/aks/cloud.env"
  value = join("\n", [
    "GCP_PROJECT_ID=${var.gcp_project_id}",
    "CORS_ALLOWED_ORIGINS=https://${azurerm_static_web_app.web.default_host_name}",
    "AZURE_TENANT_ID=${data.azurerm_client_config.current.tenant_id}",
    "AZURE_WORKLOAD_CLIENT_ID=${azurerm_user_assigned_identity.workload.client_id}",
    "AZURE_KEY_VAULT_NAME=${azurerm_key_vault.kv.name}",
    "CLOUD_SQL_INSTANCE=${google_sql_database_instance.db.connection_name}",
    "GCP_WIF_AUDIENCE=//iam.googleapis.com/${google_iam_workload_identity_pool_provider.aks.name}",
    "DNS_LABEL=${var.dns_label}",
    "API_HOST=${local.api_host}",
    "CLINICIAN_EMAILS=${join(",", var.clinician_emails)}",
    "ADMIN_EMAILS=${join(",", var.admin_emails)}",
    "",
  ])
}

output "gcp_credential_config" {
  description = "Contents for infra/k8s/overlays/aks/credential-config.json (not a secret)"
  value = jsonencode({
    type               = "external_account"
    audience           = "//iam.googleapis.com/${google_iam_workload_identity_pool_provider.aks.name}"
    subject_token_type = "urn:ietf:params:oauth:token-type:jwt"
    token_url          = "https://sts.googleapis.com/v1/token"
    credential_source  = { file = "/var/run/gcp/token" }
    service_account_impersonation_url = (
      "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/${google_service_account.workload.email}:generateAccessToken"
    )
  })
}

output "github_variables" {
  description = "GitHub Actions variables for .github/workflows/deploy.yml"
  value = {
    AZURE_CLIENT_ID       = azuread_application.github.client_id
    AZURE_TENANT_ID       = data.azurerm_client_config.current.tenant_id
    AZURE_SUBSCRIPTION_ID = var.azure_subscription_id
    AZURE_RESOURCE_GROUP  = azurerm_resource_group.main.name
    AKS_NAME              = azurerm_kubernetes_cluster.aks.name
    ACR_LOGIN_SERVER      = azurerm_container_registry.acr.login_server
    STATIC_WEB_APP_NAME   = azurerm_static_web_app.web.name
    API_HOST              = local.api_host
    FIREBASE_AUTH_DOMAIN  = "${var.gcp_project_id}.firebaseapp.com"
    FIREBASE_API_KEY      = google_apikeys_key.web.key_string
  }
  # The browser key is public by design, but keep it out of plan logs anyway
  sensitive = true
}

output "frontend_url" {
  value = "https://${azurerm_static_web_app.web.default_host_name}"
}

output "api_url" {
  value = "https://${local.api_host}"
}
