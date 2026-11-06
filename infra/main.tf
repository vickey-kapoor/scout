locals {
  image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.scout.repository_id}/${var.service_name}:${var.image_tag}"

  # env var name in the container => Secret Manager secret id
  secrets = {
    ANTHROPIC_API_KEY = "${var.service_name}-anthropic-api-key"
    TAVILY_API_KEY    = "${var.service_name}-tavily-api-key"
  }
}

# ---------------------------------------------------------------------------
# APIs
# ---------------------------------------------------------------------------

resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudbuild.googleapis.com", # only needed if you build with `gcloud builds submit`
  ])

  service            = each.value
  disable_on_destroy = false
}

# ---------------------------------------------------------------------------
# Container registry
# ---------------------------------------------------------------------------

resource "google_artifact_registry_repository" "scout" {
  repository_id = var.service_name
  location      = var.region
  format        = "DOCKER"
  description   = "Container images for ${var.service_name}"

  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# Secrets — Terraform creates the empty secrets only. Add the actual key
# values with gcloud (see infra/README.md) so they never enter TF state.
# ---------------------------------------------------------------------------

resource "google_secret_manager_secret" "keys" {
  for_each  = local.secrets
  secret_id = each.value

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# Runtime identity — the service runs as its own account with access to
# exactly these two secrets and nothing else.
# ---------------------------------------------------------------------------

resource "google_service_account" "scout" {
  account_id   = "${var.service_name}-run"
  display_name = "${var.service_name} Cloud Run runtime"
}

resource "google_secret_manager_secret_iam_member" "access" {
  for_each  = google_secret_manager_secret.keys
  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.scout.email}"
}

# ---------------------------------------------------------------------------
# Cloud Run service
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "scout" {
  name                = var.service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = var.deletion_protection

  template {
    service_account = google_service_account.scout.email
    timeout         = "300s" # an agent run can take several model + tool rounds

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    max_instance_request_concurrency = 10

    containers {
      image = local.image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle          = true # only billed for CPU while handling requests
        startup_cpu_boost = true # extra CPU during cold start; imports are slow on 1 vCPU
      }

      dynamic "env" {
        for_each = local.secrets
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.keys[env.key].secret_id
              version = "latest"
            }
          }
        }
      }

      # Cold start takes ~13s+ (Python imports on a throttled vCPU). The default
      # probe (3 checks x 10s) left almost no margin and cold starts began failing.
      # This allows up to 5 + 24 x 5 = ~125s before the instance is marked failed.
      startup_probe {
        initial_delay_seconds = 5
        period_seconds        = 5
        timeout_seconds       = 3
        failure_threshold     = 24
        http_get {
          path = "/"
        }
      }
    }
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_iam_member.access,
  ]
}

# Private by default: only the listed members may invoke the service.
resource "google_cloud_run_v2_service_iam_member" "invokers" {
  for_each = toset(var.invoker_members)
  name     = google_cloud_run_v2_service.scout.name
  location = google_cloud_run_v2_service.scout.location
  role     = "roles/run.invoker"
  member   = each.value
}
