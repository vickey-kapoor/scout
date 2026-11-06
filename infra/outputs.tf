output "service_url" {
  description = "Cloud Run URL. Call it with an identity token (service is private)."
  value       = google_cloud_run_v2_service.scout.uri
}

output "image" {
  description = "Image path to build and push to before applying."
  value       = local.image
}

output "secret_ids" {
  description = "Secret Manager secrets to add key versions to."
  value       = { for k, s in google_secret_manager_secret.keys : k => s.secret_id }
}

output "service_account" {
  description = "Runtime service account."
  value       = google_service_account.scout.email
}
