variable "prefix" {
  description = "Short lowercase name used in resource names (letters and digits only)."
  type        = string
  default     = "clinicportal"

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{2,15}$", var.prefix))
    error_message = "Use 3-16 lowercase letters and digits, starting with a letter."
  }
}

# --- Azure -------------------------------------------------------------------------------------

variable "azure_subscription_id" {
  description = "Azure subscription that hosts the shared resources (docs/cloud-accounts.md)."
  type        = string
}

variable "azure_location" {
  description = "Azure region for AKS, ACR and Key Vault."
  type        = string
  default     = "eastus"
}

variable "static_web_app_location" {
  description = "Static Web Apps is only offered in a few regions."
  type        = string
  default     = "eastus2"
}

variable "aks_node_size" {
  description = "VM size of the single AKS node. B-series keeps student credits going."
  type        = string
  default     = "Standard_B2s"
}

variable "dns_label" {
  description = "DNS label for the API: <dns_label>.<azure_location>.cloudapp.azure.com. Must be unique in the region."
  type        = string
}

# --- Google Cloud ------------------------------------------------------------------------------

variable "gcp_project_id" {
  description = "Google Cloud project for Cloud SQL, Vertex AI and Identity Platform."
  type        = string
}

variable "gcp_region" {
  description = "Region for Cloud SQL and Vertex AI."
  type        = string
  default     = "us-central1"
}

variable "gcp_billing_account" {
  description = "Billing account ID (XXXXXX-XXXXXX-XXXXXX) for the budget alert."
  type        = string
}

variable "cloud_sql_tier" {
  description = "Smallest shared-core tier is enough for the demo."
  type        = string
  default     = "db-f1-micro"
}

# --- People and money --------------------------------------------------------------------------

variable "budget_amount_usd" {
  description = "Monthly budget per cloud. Alerts at 25%, 50%, 80% and 100%."
  type        = number
  default     = 50
}

variable "budget_alert_emails" {
  description = "Who gets budget alert emails (the three of us)."
  type        = list(string)
}

variable "clinician_emails" {
  description = "Emails that get the clinician role when they sign in with Identity Platform."
  type        = list(string)
  default     = []
}

variable "admin_emails" {
  description = "Emails that get the admin role when they sign in with Identity Platform."
  type        = list(string)
  default     = []
}

# --- GitHub ------------------------------------------------------------------------------------

variable "github_repository" {
  description = "owner/name of the repository whose main branch may deploy (OIDC, no secrets)."
  type        = string
  default     = "TilokJahan/Clinic-portal"
}
