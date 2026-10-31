terraform {
  required_version = ">= 1.6"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.10"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 3.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # State lives in a private Azure Storage container (created once by hand, see infra/README.md):
  # terraform init -backend-config="storage_account_name=<state account>"
  backend "azurerm" {
    resource_group_name = "rg-clinicportal-tfstate"
    container_name      = "tfstate"
    key                 = "clinic-portal.tfstate"
    use_azuread_auth    = true
  }
}

provider "azurerm" {
  subscription_id = var.azure_subscription_id

  # Student subscriptions start with few providers registered; register exactly what we use
  resource_provider_registrations = "none"
  resource_providers_to_register = [
    "Microsoft.CognitiveServices",
    "Microsoft.ContainerRegistry",
    "Microsoft.ContainerService",
    "Microsoft.Consumption",
    "Microsoft.DBforPostgreSQL",
    "Microsoft.KeyVault",
    "Microsoft.ManagedIdentity",
    "Microsoft.Network",
    "Microsoft.Storage",
  ]

  features {
    key_vault {
      # Course project: let `terraform destroy` really remove the vault
      purge_soft_delete_on_destroy = true
    }
    cognitive_account {
      purge_soft_delete_on_destroy = true
    }
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
}

provider "azuread" {}
