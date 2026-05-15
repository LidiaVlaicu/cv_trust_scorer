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

## Pipeline

### Pipeline reprocesses all CVs after adding `content_hash` column

**Symptom**
After materializing `extract_raw_text`, the logs show `[REPROCESS changed]`
for every CV in BigQuery, even though no PDFs were modified in GCS.

**Cause**
The `content_hash` column was added to the bronze tables after the initial
batch of CVs was already ingested. Existing rows had `NULL` in the new
column. The idempotency check compares stored hash vs. current hash:

```python
if existing[submission_id] == current_hash:
    skip
else:
    reprocess
```

`None != "<any hash>"` is always True, so every existing row looks "changed"
and gets reprocessed on the first run after the column was added.

**Resolution**
This is a one-time event. The reprocessing run populates `content_hash`
for all existing rows. Subsequent runs skip unchanged CVs correctly
(`[SKIP unchanged]`).

**How to avoid next time**
When adding a column that participates in change-detection or idempotency
logic, either:
1. Backfill the column for existing rows before the next pipeline run, or
2. Accept that the next run will reprocess everything (and budget for the
   API cost — in our case ~300 Claude calls).

A backfill script for option 1 would: list all PDFs in GCS, compute hashes,
and `UPDATE ... SET content_hash = ? WHERE submission_id = ?` for each.

### 'ExtractedCV' object has no attribute 'get'

**Symptom**:

`AttributeError: 'ExtractedCV' object has no attribute 'get'`
Raised inside the extract_entities asset, once per CV, on the first line that reads a field from the Claude response:
candidate_name = cv_data.get("candidate_name", "")

**Cause**:
extract_cv_data_with_claude() returns a Pydantic model instance (ExtractedCV), not a dict. Pydantic models expose their fields as attributes, not dict keys, so .get() and ["key"] both fail. The bug typically appears after refactoring the extraction function to return a validated model while leaving the consumer code written against the old dict-returning version.

**Fix**:
Use attribute access throughout the asset:

# Fails:
candidate_name = cv_data.get("candidate_name", "")
work_experience_list = cv_data.get("work_experience", [])

# Works:
candidate_name = cv_data.candidate_name
work_experience_list = cv_data.work_experience

For iteration, the items inside work_experience are also Pydantic models, so the same rule applies:
for exp in cv_data.work_experience:
    company = exp.company_name      # attribute, not exp["company_name"]

When a plain dict is genuinely needed — JSON serialization for the GCS backup, building rows for insert_rows_json — convert explicitly at that point:
`save_json_to_gcs(cv_data.model_dump(), gcs_path)`

**How to avoid next time**: type-hint the return value of extract_cv_data_with_claude as -> ExtractedCV. Editors and linters will then flag .get() calls on the result before the code is ever run.

### NULL values appear systematically in bronze table columns

**Symptom**:

A bronze table has columns where all rows (or a clear subset) are NULL. Example:

```sql
SELECT candidate_name, email FROM raw_candidates LIMIT 10
-- returns NULL, NULL across all rows
```

The data clearly exists somewhere (e.g. in a GCS backup, in logs) but is not in the table.

**Cause**: more than one asset is responsible for populating different columns of the same table, but only one of them actually writes to it. The other asset extracts the data but never persists it to BigQuery. This violates the single-writer-per-table rule.

**Fix**: split the table so each resulting table has exactly one writing asset. Use `submission_id` (or your equivalent primary key) as the join key for downstream queries. See DESIGN_DECISIONS.md "Bronze schema: one table per asset" for the full rationale.

**How to avoid next time**: when adding a new column to a bronze table, identify which existing asset will populate it. If the answer is "a new asset would need to," that's a sign the table needs to be split rather than extended.

### Technical CV silently skipped as `non_technical`

**Symptom**:

`extract_entities` materializes successfully but inserts fewer rows than expected. Logs show `[SKIP non-technical] cv_XXX` for a CV that is clearly technical (e.g. a BI Analyst, junior data role, or any specialism whose vocabulary differs from the mainstream software/data engineering list).

A sanity SQL query like:

```sql
SELECT submission_id
FROM raw_cv_texts
WHERE submission_id NOT IN (SELECT submission_id FROM raw_candidates)
```

returns rows that should have been processed.

**Cause**: `TECHNICAL_KEYWORDS` in `extraction.py` is missing vocabulary for the CV's specialism. The classifier requires 3+ keyword matches; CVs whose primary tools aren't in the list fall below the threshold. Common gaps: BI tooling (power bi, dax, tableau), security (penetration testing, burp suite), embedded (rtos, fpga), mobile (swiftui, jetpack compose).

**Fix**: extend `TECHNICAL_KEYWORDS` with vocabulary for the missing specialism, then reprocess the affected CV:

```sql
DELETE FROM raw_cv_texts WHERE submission_id = '<the_failing_id>'
```

Then re-materialize `extract_raw_text` (it picks up only the deleted CV thanks to the `content_hash` idempotency check) followed by `extract_entities`. Cost: ~$0.001 per CV.

**How to avoid next time**: when ingesting CVs from a new specialism, spot-check that representative keyword vocabulary appears in `TECHNICAL_KEYWORDS` before running the full pipeline. The classifier is a coarse pre-filter, not an accurate classifier — see DESIGN_DECISIONS.md "Profile classification" for the design rationale.