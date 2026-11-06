# infra — Cloud Run deployment (Terraform)

Creates:

| Resource | Purpose |
|---|---|
| Project APIs | Cloud Run, Artifact Registry, Secret Manager, Cloud Build |
| Artifact Registry repo `scout` | Holds the container image |
| Secrets `scout-anthropic-api-key`, `scout-tavily-api-key` | Empty containers — you add the values with gcloud, so keys never enter Terraform state |
| Service account `scout-run` | Runtime identity; can read only those two secrets |
| Cloud Run service `scout` | Private (no `allUsers`), scales 0 → 2, 300 s timeout |
| `run.invoker` bindings | Only for the members in `invoker_members` |

## First deploy

The service needs an image and secret values to exist before it can start, so the first run is in three steps.

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # set project_id, invoker_members
terraform init

# 1. Create the registry and the (empty) secrets first
terraform apply \
  -target=google_artifact_registry_repository.scout \
  -target=google_secret_manager_secret.keys

# 2a. Add the key values (typed in, not saved to a file or TF state)
printf '%s' 'sk-ant-...' | gcloud secrets versions add scout-anthropic-api-key --data-file=-
printf '%s' 'tvly-...'   | gcloud secrets versions add scout-tavily-api-key    --data-file=-

# 2b. Build and push the image (from the repo root)
cd ..
gcloud builds submit --tag "$(terraform -chdir=infra output -raw image)" .
cd infra

# 3. Create everything else, including the Cloud Run service
terraform apply
```

## Calling it

The service is private, so send an identity token:

```bash
URL=$(terraform output -raw service_url)
curl -X POST "$URL/ask" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"question": "Who created Python?"}'
```

## Deploying a new version

```bash
gcloud builds submit --tag "$(terraform -chdir=infra output -raw image)" .
terraform -chdir=infra apply -var image_tag=latest   # or push a new tag and pass it here
```

With the `latest` tag, Terraform sees no change. Either push a unique tag (for example the git SHA) and pass it as `image_tag`, or run `gcloud run services update scout --image <image> --region <region>` to roll out the new image.

## Tearing down

```bash
terraform apply -var deletion_protection=false
terraform destroy
```

## Notes

- `traces/` is written to the container's temporary disk and is lost on restart.
- State is local (`terraform.tfstate`, gitignored). Use the commented `gcs` backend in `versions.tf` for shared state.
