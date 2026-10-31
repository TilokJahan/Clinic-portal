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
  description = "VM size of the single AKS node. B-series keeps student credits going."
  type        = string
  default     = "Standard_B2s"
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

# --- Sign-in (Microsoft Entra External ID) -----------------------------------------------------
# The external tenant, its sign-up/sign-in user flow and the app registration are created once in
# the Entra admin center (steps in infra/README.md); paste their IDs here.

variable "entra_tenant_id" {
  description = "Directory (tenant) ID of the Entra External ID tenant."
  type        = string
}

variable "entra_tenant_subdomain" {
  description = "The tenant's subdomain, as in <subdomain>.ciamlogin.com."
  type        = string
}

variable "entra_client_id" {
  description = "Application (client) ID of the frontend's app registration in the external tenant."
  type        = string
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

variable "github_repository" {
  description = "owner/name of the repository whose main branch may deploy (OIDC, no secrets)."
  type        = string
  default     = "TilokJahan/Clinic-portal"
}
