# Everything the deploy workflow needs. infra/scripts/export-github-vars.sh copies these into
# GitHub Actions variables, so the workflow never needs access to Terraform state.

output "cloud_env" {
  description = "Contents for infra/k8s/overlays/aks/cloud.env"
  value = join("\n", [
    "AUTH_MODE=${var.auth_mode}",
    "AZURE_TENANT_ID=${data.azurerm_client_config.current.tenant_id}",
    "AZURE_WORKLOAD_CLIENT_ID=${azurerm_user_assigned_identity.workload.client_id}",
    "AZURE_KEY_VAULT_NAME=${azurerm_key_vault.kv.name}",
    "AZURE_OPENAI_ENDPOINT=${azurerm_cognitive_account.openai.endpoint}",
    "AZURE_OPENAI_DEPLOYMENT=${azurerm_cognitive_deployment.triage.name}",
    "LAB_STORAGE=azure-blob",
    "LAB_STORAGE_ACCOUNT_URL=${azurerm_storage_account.labs.primary_blob_endpoint}",
    "LAB_STORAGE_CONTAINER=${azurerm_storage_container.lab_reports.name}",
    "LAB_EXTRACTOR=azure-document-intelligence",
    "DOCINTEL_ENDPOINT=${azurerm_cognitive_account.docintel.endpoint}",
    "ENTRA_TENANT_ID=${var.entra_tenant_id}",
    "ENTRA_TENANT_SUBDOMAIN=${var.entra_tenant_subdomain}",
    "ENTRA_CLIENT_ID=${var.entra_client_id}",
    "DNS_LABEL=${var.dns_label}",
    "APP_HOST=${local.app_host}",
    "CLINICIAN_EMAILS=${join(",", var.clinician_emails)}",
    "ADMIN_EMAILS=${join(",", var.admin_emails)}",
    "",
  ])
}

output "github_variables" {
  description = "GitHub Actions variables for .github/workflows/deploy.yml (none are secrets)"
  value = {
    AZURE_CLIENT_ID       = var.enable_github_deploy_identity ? azuread_application.github[0].client_id : ""
    AZURE_TENANT_ID       = data.azurerm_client_config.current.tenant_id
    AZURE_SUBSCRIPTION_ID = var.azure_subscription_id
    AZURE_RESOURCE_GROUP  = azurerm_resource_group.main.name
    AKS_NAME              = azurerm_kubernetes_cluster.aks.name
    ACR_LOGIN_SERVER      = azurerm_container_registry.acr.login_server
    APP_HOST              = local.app_host
    FRONTEND_AUTH_MODE    = var.auth_mode == "dev" ? "dev" : "entra"
    ENTRA_CLIENT_ID       = var.entra_client_id
    ENTRA_AUTHORITY       = var.entra_tenant_subdomain == "" ? "" : "https://${var.entra_tenant_subdomain}.ciamlogin.com/"
  }
}

output "app_url" {
  value = "https://${local.app_host}"
}

output "openai_endpoint" {
  description = "For scripts/evaluate_ai.py (AZURE_OPENAI_ENDPOINT)"
  value       = azurerm_cognitive_account.openai.endpoint
}
