variable "project_id" {
  description = "GCP project to deploy into."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run and Artifact Registry."
  type        = string
  default     = "us-central1"
}

variable "service_name" {
  description = "Cloud Run service name (also used to name the repo, service account and secrets)."
  type        = string
  default     = "scout"
}

variable "image_tag" {
  description = "Tag of the container image in Artifact Registry to deploy."
  type        = string
  default     = "latest"
}

variable "invoker_members" {
  description = <<-EOT
    Who may call the service, e.g. ["user:you@example.com"].
    Empty = nobody without project-level run.invoker (service stays private).
    Never put "allUsers" here unless you add your own auth: every call spends API credits.
  EOT
  type        = list(string)
  default     = []
}

variable "min_instances" {
  description = "Minimum instances. 0 = scale to zero (cheapest; first request has a cold start)."
  type        = number
  default     = 0
}

variable "max_instances" {
  description = "Maximum instances. Caps cost if the endpoint gets hammered."
  type        = number
  default     = 2
}

variable "deletion_protection" {
  description = "Block `terraform destroy` of the Cloud Run service. Set false before destroying."
  type        = bool
  default     = true
}
