# Google Cloud: Cloud SQL (database), Vertex AI (Gemini), Identity Platform (sign-in),
# keyless access from AKS (Workload Identity Federation) and a budget alert.

data "google_project" "this" {}

resource "google_project_service" "apis" {
  for_each = toset([
    "aiplatform.googleapis.com",
    "apikeys.googleapis.com",
    "billingbudgets.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "identitytoolkit.googleapis.com",
    "monitoring.googleapis.com",
    "sqladmin.googleapis.com",
    "sts.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

# --- Database ----------------------------------------------------------------------------------

resource "random_password" "db" {
  length  = 32
  special = false # goes into a URL; 32 alphanumerics is plenty
}

resource "google_sql_database_instance" "db" {
  name                = "${var.prefix}-db"
  database_version    = "POSTGRES_16"
  region              = var.gcp_region
  deletion_protection = false # course project; set true for anything real

  settings {
    tier              = var.cloud_sql_tier
    edition           = "ENTERPRISE"
    availability_type = "ZONAL"
    disk_size         = 10

    ip_configuration {
      # Public IP but no authorized networks: only the Cloud SQL Auth Proxy (IAM-authorized,
      # encrypted) can connect.
      ipv4_enabled = true
      ssl_mode     = "ENCRYPTED_ONLY"
    }

    backup_configuration {
      enabled    = true
      start_time = "03:00"
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_sql_database" "clinic" {
  name     = "clinic"
  instance = google_sql_database_instance.db.name
}

resource "google_sql_user" "app" {
  name     = "clinic"
  instance = google_sql_database_instance.db.name
  password = random_password.db.result
}

# --- Service account used by the pods (through Workload Identity Federation) -------------------

resource "google_service_account" "workload" {
  account_id   = "clinic-workload"
  display_name = "Clinic portal pods on AKS"
}

resource "google_project_iam_member" "workload" {
  for_each = toset(["roles/cloudsql.client", "roles/aiplatform.user"])
  project  = var.gcp_project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.workload.email}"
}

resource "google_iam_workload_identity_pool" "aks" {
  workload_identity_pool_id = "aks-pool"
  display_name              = "AKS clinic portal"
  depends_on                = [google_project_service.apis]
}

# Trusts tokens issued by the AKS cluster's OIDC issuer
resource "google_iam_workload_identity_pool_provider" "aks" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.aks.workload_identity_pool_id
  workload_identity_pool_provider_id = "aks-oidc"
  attribute_mapping = {
    "google.subject" = "assertion.sub"
  }
  oidc {
    issuer_uri = azurerm_kubernetes_cluster.aks.oidc_issuer_url
  }
}

# Only our two Kubernetes service accounts may act as the Google service account
resource "google_service_account_iam_member" "workload" {
  for_each           = toset(local.workloads)
  service_account_id = google_service_account.workload.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principal://iam.googleapis.com/${google_iam_workload_identity_pool.aks.name}/subject/system:serviceaccount:${local.namespace}:${each.value}"
}

# --- Sign-in (Identity Platform) ---------------------------------------------------------------

resource "google_identity_platform_config" "auth" {
  project = var.gcp_project_id

  sign_in {
    email {
      enabled           = true
      password_required = true
    }
  }

  authorized_domains = [
    "localhost",
    "${var.gcp_project_id}.firebaseapp.com",
    azurerm_static_web_app.web.default_host_name,
  ]

  depends_on = [google_project_service.apis]
}

# Browser key for the sign-in page. Public by design, restricted to Identity Platform and our
# site's address.
resource "google_apikeys_key" "web" {
  name         = "${var.prefix}-web"
  display_name = "Clinic portal sign-in (browser)"

  restrictions {
    api_targets {
      service = "identitytoolkit.googleapis.com"
    }
    browser_key_restrictions {
      allowed_referrers = [
        "https://${azurerm_static_web_app.web.default_host_name}/*",
        "http://localhost:*/*",
      ]
    }
  }

  depends_on = [google_project_service.apis]
}

# --- Budget ------------------------------------------------------------------------------------

resource "google_monitoring_notification_channel" "budget" {
  for_each     = toset(var.budget_alert_emails)
  display_name = "Budget alert ${each.value}"
  type         = "email"
  labels       = { email_address = each.value }
  depends_on   = [google_project_service.apis]
}

resource "google_billing_budget" "monthly" {
  billing_account = var.gcp_billing_account
  display_name    = "${var.prefix} monthly"

  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
    # Count usage before credits, so alerts fire while credits are being used up
    credit_types_treatment = "EXCLUDE_ALL_CREDITS"
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.budget_amount_usd)
    }
  }

  dynamic "threshold_rules" {
    for_each = [0.25, 0.5, 0.8, 1.0]
    content {
      threshold_percent = threshold_rules.value
    }
  }

  all_updates_rule {
    monitoring_notification_channels = [for c in google_monitoring_notification_channel.budget : c.id]
  }

  depends_on = [google_project_service.apis]
}
