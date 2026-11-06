terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # State is local by default. For shared/CI use, store it in a GCS bucket:
  # backend "gcs" {
  #   bucket = "<your-tf-state-bucket>"
  #   prefix = "scout"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
