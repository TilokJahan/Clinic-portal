# Everything runs on Azure: AKS (app), ACR (images), PostgreSQL Flexible Server (database),
# Azure OpenAI (triage AI), Key Vault (secrets), a budget alert, and an identity GitHub Actions
# can use without any stored secret. Sign-in is Microsoft Entra External ID (see variables.tf).

data "azurerm_client_config" "current" {}

locals {
  app_host  = "${var.dns_label}.${var.location}.cloudapp.azure.com"
  namespace = "clinic-portal"
  # Kubernetes service accounts that get an Azure identity (see infra/k8s)
  workloads = ["appointment-service", "triage-service"]
  tags      = { project = "clinic-portal" }
}

resource "azurerm_resource_group" "main" {
  name     = "rg-${var.prefix}"
  location = var.location
  tags     = local.tags
}

# --- Network: AKS and the database share a private virtual network ------------------------------

resource "azurerm_virtual_network" "main" {
  name                = "vnet-${var.prefix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  address_space       = ["10.20.0.0/16"]
  tags                = local.tags
}

resource "azurerm_subnet" "aks" {
  name                 = "snet-aks"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.20.0.0/22"]
}

resource "azurerm_subnet" "postgres" {
  name                 = "snet-postgres"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = ["10.20.8.0/24"]

  delegation {
    name = "postgres"
    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }

  lifecycle {
    ignore_changes = [service_endpoints] # Azure adds Microsoft.Storage itself for PostgreSQL
  }
}

resource "azurerm_private_dns_zone" "postgres" {
  name                = "${var.prefix}.private.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "vnet-link"
  resource_group_name   = azurerm_resource_group.main.name
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  virtual_network_id    = azurerm_virtual_network.main.id
}

# --- Database ----------------------------------------------------------------------------------

resource "random_password" "db" {
  length  = 32
  special = false # goes into a URL; 32 alphanumerics is plenty
}

resource "azurerm_postgresql_flexible_server" "db" {
  name                          = "psql-${var.prefix}"
  resource_group_name           = azurerm_resource_group.main.name
  location                      = azurerm_resource_group.main.location
  version                       = "16"
  sku_name                      = var.postgres_sku
  storage_mb                    = 32768
  backup_retention_days         = 7
  administrator_login           = "clinicadmin"
  administrator_password        = random_password.db.result
  delegated_subnet_id           = azurerm_subnet.postgres.id
  private_dns_zone_id           = azurerm_private_dns_zone.postgres.id
  public_network_access_enabled = false # only reachable from inside the virtual network
  tags                          = local.tags

  lifecycle {
    ignore_changes = [zone] # Azure picks a zone; don't fight it on later plans
  }

  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgres]
}

resource "azurerm_postgresql_flexible_server_database" "clinic" {
  name      = "clinic"
  server_id = azurerm_postgresql_flexible_server.db.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# --- AI: Azure OpenAI, keyless ------------------------------------------------------------------

resource "azurerm_cognitive_account" "openai" {
  name                  = "oai-${var.prefix}"
  resource_group_name   = azurerm_resource_group.main.name
  location              = var.openai_location # where the subscription has model quota
  kind                  = "OpenAI"
  sku_name              = "S0"
  custom_subdomain_name = "oai-${var.prefix}" # required for Entra ID (token) auth
  local_auth_enabled    = false               # no API keys: Entra ID only
  tags                  = local.tags
}

resource "azurerm_cognitive_deployment" "triage" {
  name                 = var.openai_model.name
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = var.openai_model.name
    version = var.openai_model.version
  }

  sku {
    name     = var.openai_model.sku
    capacity = var.openai_model.capacity
  }
}

# --- Lab reports: private Blob Storage + Azure AI Document Intelligence (OCR), both keyless -------

resource "azurerm_storage_account" "labs" {
  name                            = "${var.prefix}labs"
  resource_group_name             = azurerm_resource_group.main.name
  location                        = azurerm_resource_group.main.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false # Entra ID only: the pods use workload identity
  tags                            = local.tags

  blob_properties {
    delete_retention_policy {
      days = 7 # an accidental delete can be undone for a week
    }
  }
}

resource "azurerm_storage_container" "lab_reports" {
  name                  = "lab-reports"
  storage_account_id    = azurerm_storage_account.labs.id
  container_access_type = "private"
}

resource "azurerm_cognitive_account" "docintel" {
  name                  = "di-${var.prefix}"
  resource_group_name   = azurerm_resource_group.main.name
  location              = azurerm_resource_group.main.location
  kind                  = "FormRecognizer" # Azure AI Document Intelligence
  sku_name              = "F0"             # free: 500 pages a month, plenty for the demo
  custom_subdomain_name = "di-${var.prefix}"
  local_auth_enabled    = false # no keys: Entra ID only
  tags                  = local.tags
}

# --- Images ------------------------------------------------------------------------------------

resource "azurerm_container_registry" "acr" {
  name                = "${var.prefix}acr"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  admin_enabled       = false # pull with the cluster identity, push with GitHub OIDC
  tags                = local.tags
}

# --- Kubernetes --------------------------------------------------------------------------------

resource "azurerm_kubernetes_cluster" "aks" {
  name                = "aks-${var.prefix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  dns_prefix          = var.prefix
  sku_tier            = "Free"

  default_node_pool {
    # "rotation" is the pool Terraform rotated to when we resized to 4 vCPU. Our regional quota (6
    # vCPU) can't hold two 4-vCPU pools at once to rotate back, and AKS can't rename pools.
    name                        = "rotation"
    temporary_name_for_rotation = "system" # a future resize rotates through this name
    vm_size                     = var.aks_node_size
    node_count                  = 1
    os_disk_size_gb             = 64
    vnet_subnet_id              = azurerm_subnet.aks.id

    # Azure's default; one extra node during upgrades fits our vCPU quota
    upgrade_settings {
      max_surge = "10%"
    }
  }

  identity {
    type = "SystemAssigned"
  }

  # Workload identity: pods get Entra tokens for their Kubernetes service account
  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_policy      = "azure" # enforces infra/k8s/base/network-policy.yaml
    service_cidr        = "10.0.0.0/16"
    dns_service_ip      = "10.0.0.10"
  }

  key_vault_secrets_provider {
    secret_rotation_enabled = true
  }

  # Managed nginx ingress (the clinic-nginx controller in infra/k8s/overlays/aks)
  web_app_routing {
    dns_zone_ids = []
    # The add-on's own default controller reserves half a CPU we don't use; we run clinic-nginx
    default_nginx_controller = "None"
  }

  tags = local.tags
}

# The cluster manages load balancers and IPs in our subnet
resource "azurerm_role_assignment" "aks_network" {
  scope                = azurerm_virtual_network.main.id
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_kubernetes_cluster.aks.identity[0].principal_id
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
  tags                       = local.tags
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
  value = format(
    "postgresql://%s:%s@%s:5432/%s?sslmode=require",
    azurerm_postgresql_flexible_server.db.administrator_login,
    random_password.db.result,
    azurerm_postgresql_flexible_server.db.fqdn,
    azurerm_postgresql_flexible_server_database.clinic.name,
  )
  depends_on = [azurerm_role_assignment.kv_terraform]
}

# Signs the demo sign-in tokens (AUTH_MODE=dev). Generated here, only ever stored in Key Vault.
resource "random_password" "auth_dev_secret" {
  length  = 48
  special = false
}

resource "azurerm_key_vault_secret" "auth_dev_secret" {
  name         = "auth-dev-secret"
  key_vault_id = azurerm_key_vault.kv.id
  value        = random_password.auth_dev_secret.result
  depends_on   = [azurerm_role_assignment.kv_terraform]
}

# --- Identity the pods use (federated with their Kubernetes service accounts) -------------------

resource "azurerm_user_assigned_identity" "workload" {
  name                = "id-${var.prefix}-workload"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.tags
}

resource "azurerm_federated_identity_credential" "workload" {
  for_each                  = toset(local.workloads)
  name                      = each.value
  user_assigned_identity_id = azurerm_user_assigned_identity.workload.id
  audience                  = ["api://AzureADTokenExchange"]
  issuer                    = azurerm_kubernetes_cluster.aks.oidc_issuer_url
  subject                   = "system:serviceaccount:${local.namespace}:${each.value}"
}

resource "azurerm_role_assignment" "workload" {
  for_each = {
    key_vault = { scope = azurerm_key_vault.kv.id, role = "Key Vault Secrets User" }
    openai    = { scope = azurerm_cognitive_account.openai.id, role = "Cognitive Services OpenAI User" }
    lab_files = { scope = azurerm_storage_account.labs.id, role = "Storage Blob Data Contributor" }
    docintel  = { scope = azurerm_cognitive_account.docintel.id, role = "Cognitive Services User" }
  }
  scope                = each.value.scope
  role_definition_name = each.value.role
  principal_id         = azurerm_user_assigned_identity.workload.principal_id
}

# Lets whoever runs Terraform try the model from a laptop (scripts/evaluate_ai.py with az login)
resource "azurerm_role_assignment" "openai_terraform" {
  scope                = azurerm_cognitive_account.openai.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = data.azurerm_client_config.current.object_id
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

# --- GitHub Actions deploy identity (OIDC, no secrets), optional ------------------------------
# Off by default: the WMICH tenant lets us create app registrations but not federated credentials.
# Without it, deploy from a laptop with infra/scripts/deploy.sh (same steps as deploy.yml).

resource "azuread_application" "github" {
  count        = var.enable_github_deploy_identity ? 1 : 0
  display_name = "github-${var.prefix}-deploy"
}

resource "azuread_service_principal" "github" {
  count     = var.enable_github_deploy_identity ? 1 : 0
  client_id = azuread_application.github[0].client_id
}

resource "azuread_application_federated_identity_credential" "github_main" {
  count          = var.enable_github_deploy_identity ? 1 : 0
  application_id = azuread_application.github[0].id
  display_name   = "main-branch"
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = "repo:${var.github_repository}:ref:refs/heads/main"
}

resource "azurerm_role_assignment" "github" {
  for_each = var.enable_github_deploy_identity ? {
    acr_push = { scope = azurerm_container_registry.acr.id, role = "AcrPush" }
    aks_user = { scope = azurerm_kubernetes_cluster.aks.id, role = "Azure Kubernetes Service Cluster User Role" }
  } : {}
  scope                = each.value.scope
  role_definition_name = each.value.role
  principal_id         = azuread_service_principal.github[0].object_id
}
