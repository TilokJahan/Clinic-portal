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
    google = {
      source  = "hashicorp/google"
      version = "~> 6.10"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # State lives in a private Google Cloud Storage bucket (created once by hand, see README).
  # terraform init -backend-config="bucket=<state bucket>"
  backend "gcs" {
    prefix = "clinic-portal"
  }
}

provider "azurerm" {
  subscription_id = var.azure_subscription_id
  features {
    key_vault {
      # Course project: let `terraform destroy` really remove the vault
      purge_soft_delete_on_destroy = true
    }
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
}

provider "azuread" {}

provider "google" {
  project = var.gcp_project_id
  region  = var.gcp_region
  # Needed so APIs like billingbudgets and apikeys bill to this project
  user_project_override = true
  billing_project       = var.gcp_project_id
}
