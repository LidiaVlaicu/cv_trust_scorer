# Setup

Step-by-step instructions to set up the CV Trust Scorer development environment from a fresh clone.

## Prerequisites

- macOS or Linux (commands assume zsh or bash)
- Python 3.11 or higher
- `gcloud` CLI installed: see https://cloud.google.com/sdk/docs/install
- Access to a Google Cloud project with billing enabled
- Owner role on the GCP project (or, at minimum, the ability to create service accounts and grant the Token Creator role)

## 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/cv-trust_scorer.git
cd cv-trust_scorer
```

## 2. Set up the Python virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Verify you are inside the venv:

```bash
which python
```

Should show a path inside `venv/bin/`.

## 3. Configure environment variables

Copy the example and fill in your values:

```bash
cp .env.example .env
```

Open `.env` in your editor and set:

- `GCP_PROJECT_ID`: your Google Cloud project ID
- `GCP_LOCATION`: the region for BigQuery (recommended: `EU` or `europe-west1`)
- Other variables as listed in the file

## 4. Authenticate gcloud

Sign in as the human admin account that has Owner (or equivalent) permissions on the project.

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

Verify:

```bash
gcloud config list
```

## 5. Create the pipeline service account

If the service account does not already exist:

```bash
PROJECT_ID=$(gcloud config get-value project)
SA_EMAIL="cv-trust-scorer-runner@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts create cv-trust-scorer-runner \
    --display-name="CV Trust Scorer Pipeline Runner" \
    --description="Service account for the CV Trust Scorer data pipeline"
```

## 6. Grant IAM roles to the service account

The pipeline needs three scoped roles:

```bash
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/storage.objectAdmin"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/bigquery.dataEditor"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/bigquery.jobUser"
```

Verify:

```bash
gcloud projects get-iam-policy ${PROJECT_ID} \
    --flatten="bindings[].members" \
    --filter="bindings.members:cv-trust-scorer-runner" \
    --format="table(bindings.role)"
```

Expected output lists the three roles.

## 7. Grant your account permission to impersonate the service account

```bash
gcloud iam service-accounts add-iam-policy-binding ${SA_EMAIL} \
    --member="user:YOUR_EMAIL@gmail.com" \
    --role="roles/iam.serviceAccountTokenCreator"
```

Replace `YOUR_EMAIL@gmail.com` with the admin account email.

## 8. Set up Application Default Credentials with impersonation

```bash
gcloud auth application-default login \
    --impersonate-service-account=${SA_EMAIL}
```

A browser opens. Sign in as the admin account and grant consent.

This creates an ADC file at `~/.config/gcloud/application_default_credentials.json` configured to obtain short-lived impersonation tokens automatically.

## 9. Verify the authentication setup

```bash
python scripts/path_auth.py
```

Expected output:

```
Credentials type: ImpersonatedCredentials
Service account: cv-trust-scorer-runner@YOUR_PROJECT_ID.iam.gserviceaccount.com
Token expires at: ...
Token lifetime: 60.0 minutes
Project: YOUR_PROJECT_ID
Authenticated as: cv-trust-scorer-runner@YOUR_PROJECT_ID.iam.gserviceaccount.com

Authentication is correctly configured.
```

The `Authenticated as` line must show the service account email (ending in `gserviceaccount.com`), not a human account.

## 10. Set up budget alerts

To prevent unexpected costs, configure a billing budget in the Cloud Console:

1. Go to Billing → Budgets & alerts.
2. Create a budget with a monthly limit (suggested: €5 for development).
3. Add alert thresholds at 50%, 80%, and 100%.

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common issues.

## Notes

- The venv must be activated in every new terminal session: `source venv/bin/activate`.
- Impersonation tokens expire after one hour; the Google client libraries refresh them automatically.
- If your gcloud session expires, re-run step 8 to refresh the ADC file.