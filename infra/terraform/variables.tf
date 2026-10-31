variable "prefix" {
  description = "Short lowercase name used in resource names (letters and digits only)."
  type        = string
  default     = "clinicportal"

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{2,15}$", var.prefix))
    error_message = "Use 3-16 lowercase letters and digits, starting with a letter."
  }
}

variable "azure_subscription_id" {
  description = "Azure subscription that hosts everything (docs/cloud-accounts.md)."
  type        = string
}

variable "location" {
  description = "Azure region. Azure for Students only allows a few (ours: canadacentral, francecentral, belgiumcentral, denmarkeast, mexicocentral)."
  type        = string
  default     = "canadacentral"
}

variable "aks_node_size" {
  description = "VM size of the single AKS node. Our Azure for Students subscription only has vCPU quota for B-series v2, and AKS only accepts the ARM ones there. B4ps_v2 (4 vCPU, 16 GB): AKS system pods alone reserve ~1.2 CPU, so 2 vCPU didn't fit the app. Images are built for arm64 and amd64."
  type        = string
  default     = "Standard_B4ps_v2"
}

variable "postgres_sku" {
  description = "Azure Database for PostgreSQL Flexible Server size. B1ms (burstable) is enough for the demo."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "openai_location" {
  description = "Region for Azure OpenAI. Our student subscription has chat-model quota in francecentral but not canadacentral (az cognitiveservices usage list -l <region>)."
  type        = string
  default     = "francecentral"
}

variable "openai_model" {
  description = "Azure OpenAI model for triage. gpt-5-mini: generally available, supported until 2027-02, 500K TPM quota on our subscription."
  type = object({
    name     = string
    version  = string
    sku      = string
    capacity = number # thousands of tokens per minute
  })
  default = {
    name     = "gpt-5-mini"
    version  = "2025-08-07"
    sku      = "GlobalStandard"
    capacity = 50
  }
}

variable "dns_label" {
  description = "DNS label for the app: <dns_label>.<location>.cloudapp.azure.com. Must be unique in the region."
  type        = string
}

# --- Sign-in -------------------------------------------------------------------------------------
# "dev": the synthetic demo accounts (what we run: our university tenant blocks both an External ID
# tenant (region policy) and user consent to apps). "entra-external-id": real sign-up/sign-in;
# fill in the three entra_* values from an External ID tenant (infra/README.md).

variable "auth_mode" {
  description = "dev (demo accounts) or entra-external-id."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "entra-external-id"], var.auth_mode)
    error_message = "auth_mode must be dev or entra-external-id."
  }
}

variable "entra_tenant_id" {
  description = "Directory (tenant) ID of the Entra External ID tenant (entra-external-id only)."
  type        = string
  default     = ""
}

variable "entra_tenant_subdomain" {
  description = "The tenant's subdomain, as in <subdomain>.ciamlogin.com (entra-external-id only)."
  type        = string
  default     = ""
}

variable "entra_client_id" {
  description = "Application (client) ID of the frontend's app registration (entra-external-id only)."
  type        = string
  default     = ""
}

# --- People and money --------------------------------------------------------------------------

variable "budget_amount_usd" {
  description = "Monthly budget. Alerts at 25%, 50%, 80% and 100%."
  type        = number
  default     = 50
}

variable "budget_alert_emails" {
  description = "Who gets budget alert emails (the three of us)."
  type        = list(string)
}

variable "clinician_emails" {
  description = "Emails that get the clinician role when they sign in."
  type        = list(string)
  default     = []
}

variable "admin_emails" {
  description = "Emails that get the admin role when they sign in."
  type        = list(string)
  default     = []
}

variable "enable_github_deploy_identity" {
  description = "Create an app registration so GitHub Actions can deploy with OIDC. Our university tenant refuses the federated credential, so it's off and we deploy with infra/scripts/deploy.sh."
  type        = bool
  default     = false
}

variable "github_repository" {
  description = "owner/name of the repository whose main branch may deploy (OIDC, no secrets)."
  type        = string
  default     = "TilokJahan/Clinic-portal"
}
