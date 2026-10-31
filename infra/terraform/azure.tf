# Azure: AKS (services), ACR (images), Key Vault (secrets), Static Web Apps (frontend),
# a budget alert, and an identity GitHub Actions can use without any stored secret.

data "azurerm_client_config" "current" {}

locals {
  api_host  = "${var.dns_label}.${var.azure_location}.cloudapp.azure.com"
  namespace = "clinic-portal"
  # Kubernetes service accounts that need cloud access (see infra/k8s/base)
  workloads = ["appointment-service", "triage-service"]
}

resource "azurerm_resource_group" "main" {
  name     = "rg-${var.prefix}"
  location = var.azure_location
  tags     = { project = "clinic-portal" }
}

# --- Images ------------------------------------------------------------------------------------

resource "azurerm_container_registry" "acr" {
  name                = "${var.prefix}acr"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  admin_enabled       = false # pull with the cluster identity, push with GitHub OIDC
}

# --- Kubernetes --------------------------------------------------------------------------------

resource "azurerm_kubernetes_cluster" "aks" {
  name                = "aks-${var.prefix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  dns_prefix          = var.prefix
  sku_tier            = "Free"

  default_node_pool {
    name            = "system"
    vm_size         = var.aks_node_size
    node_count      = 1
    os_disk_size_gb = 64
  }

  identity {
    type = "SystemAssigned"
  }

  # Workload identity: pods get Azure tokens for their Kubernetes service account
  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_policy      = "azure" # enforces infra/k8s/base/network-policy.yaml
  }

  key_vault_secrets_provider {
    secret_rotation_enabled = true
  }

  # Managed nginx ingress (the clinic-nginx controller in infra/k8s/overlays/aks)
  web_app_routing {
    dns_zone_ids = []
  }

  tags = azurerm_resource_group.main.tags
}

resource "azurerm_role_assignment" "aks_pull" {
  scope                            = azurerm_container_registry.acr.id
  role_definition_name             = "AcrPull"
  principal_id                     = azurerm_kubernetes_cluster.aks.kubelet_identity[0].object_id
  skip_service_principal_aad_check = true
}

# --- Secrets -----------------------------------------------------------------------------------

resource "azurerm_key_vault" "kv" {
  name                       = "kv-${var.prefix}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  soft_delete_retention_days = 7
  purge_protection_enabled   = false
}

# Whoever runs Terraform may write secrets
resource "azurerm_role_assignment" "kv_terraform" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_key_vault_secret" "database_url" {
  name         = "database-url"
  key_vault_id = azurerm_key_vault.kv.id
  # The Cloud SQL Auth Proxy sidecar listens on 127.0.0.1:5432 in the appointment pod
  value      = "postgresql://${google_sql_user.app.name}:${random_password.db.result}@127.0.0.1:5432/${google_sql_database.clinic.name}"
  depends_on = [azurerm_role_assignment.kv_terraform]
}

# Identity the pods use for Key Vault (federated with their Kubernetes service accounts)
resource "azurerm_user_assigned_identity" "workload" {
  name                = "id-${var.prefix}-workload"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
}

resource "azurerm_federated_identity_credential" "workload" {
  for_each            = toset(local.workloads)
  name                = each.value
  resource_group_name = azurerm_resource_group.main.name
  parent_id           = azurerm_user_assigned_identity.workload.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.aks.oidc_issuer_url
  subject             = "system:serviceaccount:${local.namespace}:${each.value}"
}

resource "azurerm_role_assignment" "kv_workload" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.workload.principal_id
}

# --- Frontend ----------------------------------------------------------------------------------

resource "azurerm_static_web_app" "web" {
  name                = "swa-${var.prefix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.static_web_app_location
  sku_tier            = "Free"
  sku_size            = "Free"
}

# --- Budget ------------------------------------------------------------------------------------

resource "azurerm_consumption_budget_resource_group" "monthly" {
  name              = "budget-${var.prefix}"
  resource_group_id = azurerm_resource_group.main.id
  amount            = var.budget_amount_usd
  time_grain        = "Monthly"

  time_period {
    start_date = formatdate("YYYY-MM-01'T'00:00:00Z", timestamp())
  }

  dynamic "notification" {
    for_each = [25, 50, 80, 100]
    content {
      enabled        = true
      threshold      = notification.value
      operator       = "GreaterThanOrEqualTo"
      threshold_type = "Actual"
      contact_emails = var.budget_alert_emails
    }
  }

  lifecycle {
    ignore_changes = [time_period] # start date is fixed at creation
  }
}

# --- GitHub Actions deploy identity (OIDC, no secrets) -----------------------------------------
# Student tenants sometimes block app registrations; see infra/README.md for the fallback.

resource "azuread_application" "github" {
  display_name = "github-${var.prefix}-deploy"
}

resource "azuread_service_principal" "github" {
  client_id = azuread_application.github.client_id
}

resource "azuread_application_federated_identity_credential" "github_main" {
  application_id = azuread_application.github.id
  display_name   = "main-branch"
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = "repo:${var.github_repository}:ref:refs/heads/main"
}

resource "azurerm_role_assignment" "github" {
  for_each = {
    acr_push = { scope = azurerm_container_registry.acr.id, role = "AcrPush" }
    aks_user = { scope = azurerm_kubernetes_cluster.aks.id, role = "Azure Kubernetes Service Cluster User Role" }
    swa      = { scope = azurerm_static_web_app.web.id, role = "Contributor" }
  }
  scope                = each.value.scope
  role_definition_name = each.value.role
  principal_id         = azuread_service_principal.github.object_id
}
