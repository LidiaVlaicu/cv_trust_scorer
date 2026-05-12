# Troubleshooting

Solutions to issues encountered during setup and development.

## Authentication

### `google.auth.default()` fails with INVALID_ARGUMENT on refresh

**Symptom**:

```
google.auth.exceptions.RefreshError: ('Unable to acquire impersonated credentials',
  '{"error": {"code": 400, "message": "Request contains an invalid argument.",
   "status": "INVALID_ARGUMENT"}}')
```

**Cause**: When using impersonated credentials, `google.auth.default()` must be called with explicit scopes. Without scopes, the IAM service rejects the impersonation request with a generic INVALID_ARGUMENT error.

**Fix**: pass scopes explicitly:

```python
from google.auth import default
from google.auth.transport.requests import Request

# Fails with INVALID_ARGUMENT:
credentials, project = default()
credentials.refresh(Request())

# Works:
credentials, project = default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"]
)
credentials.refresh(Request())
```

**Note**: this affects diagnostic scripts that call `default()` directly. Normal usage through high-level client libraries (`bigquery.Client()`, `storage.Client()`) handles scopes automatically because each library knows what scopes it needs.

---

### "Key creation is not allowed on this service account"

**Symptom**:

```
FAILED_PRECONDITION: Key creation is not allowed on this service account.
```

**Cause**: Google enables the `iam.disableServiceAccountKeyCreation` organization policy by default on new accounts to discourage long-lived keys.

**Resolution**: this project does not use service account JSON keys. Use the impersonation flow described in [SETUP.md](SETUP.md) instead.

If you genuinely need a JSON key (not recommended), disable the policy:

```bash
cat > /tmp/policy.yaml << 'EOF'
constraint: constraints/iam.disableServiceAccountKeyCreation
booleanPolicy:
  enforced: false
EOF

gcloud resource-manager org-policies set-policy /tmp/policy.yaml --project=YOUR_PROJECT_ID
```

---

### "Gaia id not found" or "NOT_FOUND" when impersonating

**Symptom**:

```
ERROR: Failed to impersonate [cv-trust-scorer-runner@PROJECT_ID.iam.gserviceaccount.com]
Not found; Gaia id not found for email ...
```

**Cause**: the service account email used in the impersonation command is wrong. Common causes:
- Placeholder like `YOUR_PROJECT_ID` was not replaced with the real project ID.
- Shell variable was not set when the command ran, so the email resolved to an invalid string.

**Fix**: verify the email contains the real project ID:

```bash
gcloud iam service-accounts list
```

Copy the exact email from the output. Use it literally in commands.

To avoid this in the future, set shell variables explicitly and verify them before use:

```bash
PROJECT_ID=$(gcloud config get-value project)
SA_EMAIL="cv-trust-scorer-runner@${PROJECT_ID}.iam.gserviceaccount.com"

echo "Service account: $SA_EMAIL"  # confirm this is correct before using
```

---

### `which python` shows pyenv path instead of venv

**Symptom**: even after `source venv/bin/activate`, `which python` returns a path like `~/.pyenv/shims/python`.

**Cause**: the venv was not activated, or activation did not modify the PATH correctly.

**Fix**:

```bash
cd /path/to/cv-trust_scorer
source venv/bin/activate
which python
```

Should now show `/path/to/cv-trust_scorer/venv/bin/python`.

If the venv directory does not exist, create it:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

### ImportError: cannot import name 'bigquery' from 'google.cloud'

**Cause**: the `google-cloud-bigquery` package is not installed in the active Python environment.

**Fix**:

```bash
source venv/bin/activate
pip install google-cloud-bigquery
```

Also confirm `requirements.txt` lists the package:

```bash
grep google-cloud-bigquery requirements.txt
```

If missing, add it:

```bash
pip freeze > requirements.txt
```