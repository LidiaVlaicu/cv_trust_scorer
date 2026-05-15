# Design Decisions

A record of significant technical choices in the project, their alternatives, and the reasoning behind them. Updated as new decisions are made.

## A note on trust boundaries

Several decisions in this document share a pattern. This is identifying where untrusted input enters the system like
- human credentials, 
- LLM output, 
- raw PDFs, 
- string values flowing into SQL 
and enforcing constraints exactly at that boundary, so downstream code can operate on validated data. Each relevant section flags its boundary explicitly.

---

## 1.Authentication: ADC with service account impersonation

### Decision

Local development uses Application Default Credentials with service account impersonation. CI/CD will use Workload Identity Federation (planned in week 5-6).

### Reasoning

This is the first trust boundary in the system: human identity (the developer) is exchanged for pipeline identity (the service account) at exactly one point (the ADC impersonation step) so all downstream GCP calls authenticate as the pipeline, not the human.

### Alternatives considered

**Service account JSON keys**: simplest setup, works in every environment, used by most tutorials. Rejected for local development because:
- Long-lived keys stored on disk are the most common source of GCP credential leaks (accidental commits to public repositories, paste into chat tools, leaked backups).
- Google enables a default organization policy blocking key creation on new projects, signaling that keys are no longer the preferred pattern.
- Impersonation provides the same effective access pattern (code authenticates as a service account) without persistent credentials on disk.

**Direct human user credentials**: simplest, no service account needed. Rejected because:
- Application code should not authenticate as a human identity. If the human leaves, has their account suspended, or rotates credentials, the pipeline breaks.
- Audit logs would attribute all pipeline actions to a human, making it impossible to distinguish automated operations from manual ones.
- Permissions cannot be scoped per pipeline; the human likely has much broader access than the pipeline needs.

**Workload Identity Federation locally**: cleanest pattern, no long-lived credentials. Rejected for local development because:
- Requires an OIDC token source on the local machine, which adds significant setup complexity.
- The marginal benefit over impersonation is small in a single-user development environment.
- WIF will be used for CI/CD where its strengths matter most.

### Implementation

- A dedicated service account `cv-trust-scorer-runner` is created in the GCP project.
- The service account has three scoped IAM roles: `roles/storage.objectAdmin`, `roles/bigquery.dataEditor`, `roles/bigquery.jobUser`. No broader roles like Editor or Owner.
- The human admin account is granted `roles/iam.serviceAccountTokenCreator` on the service account, allowing it to obtain impersonation tokens.
- ADC is configured via `gcloud auth application-default login --impersonate-service-account`, which writes an ADC file containing the impersonation URL but no long-lived key material.
- Google client libraries automatically detect the ADC file and obtain short-lived (1-hour) impersonation tokens for each session.
- A diagnostic script (`scripts/test_auth.py`) confirms the effective principal is the service account, not the human account.

### Production migration path

- **CI/CD on GitHub Actions**: Workload Identity Federation with GitHub OIDC tokens. No keys, no human credentials in the chain.
- **Production GCP compute (Cloud Run, Cloud Functions, GKE)**: attached service account. The compute platform provides credentials to the code automatically.
- **Production non-GCP compute**: WIF with a platform-specific OIDC provider, or short-lived impersonation tokens via a key admin service.

---

## 2.Data architecture: medallion in BigQuery

### Decision

Three-layer medallion architecture (bronze, silver, gold) implemented as three BigQuery datasets within a single project.

### Reasoning

- Industry standard for data lakehouse and warehouse design.
- Each layer has a clear purpose: bronze for raw ingestion, silver for normalization and validation, gold for business-level outputs.
- Maps cleanly to dbt's staging / intermediate / marts model organization.
- Familiar to hiring managers and easy to explain.

### Alternatives considered

- **Two-layer (raw and processed)**: simpler but loses the distinction between cleaned data and analytics-ready outputs.
- **Single dataset with naming conventions**: works for small projects but doesn't scale; permissions and lifecycle management are easier per-dataset.

---

## 3.Orchestration: Dagster OSS

### Decision

Self-hosted Dagster OSS for pipeline orchestration, running locally in Docker during development.

### Reasoning

- Modern orchestrator with strong asset-based abstractions that match the data lineage pattern.
- OSS version is free and fully featured for development.
- Hiring relevance is good: Dagster is increasingly common in DE job descriptions alongside Airflow and Prefect.

### Alternatives considered

- **Airflow**: most widely used in industry, highest hiring relevance. Considered but rejected for this project because Dagster's asset model and developer experience are significantly better for a portfolio piece, and Airflow knowledge can be demonstrated on a future project.
- **Prefect**: similar to Dagster, slightly different mental model. No strong reason to prefer either; chose Dagster for its asset-based design.
- **Dagster+ (managed)**: rejected. Adds cost and external dependency without proportional benefit for a portfolio project. Self-hosting demonstrates infrastructure understanding.

---

## 4.Transformations: dbt with BigQuery adapter

### Decision

Use dbt for all SQL transformations between layers (bronze to silver, silver to gold).

### Reasoning

- Industry standard for warehouse transformations.
- Provides built-in testing, documentation, and lineage tracking.
- Strongly expected in modern DE job descriptions.
- Integrates cleanly with BigQuery via `dbt-bigquery`.

### Alternatives considered

- **Raw SQL scripts**: works but loses dbt's testing, dependency management, and documentation.
- **dbt-core vs dbt-cloud**: dbt-core (free, self-managed) chosen over dbt-cloud (managed, paid) for the same reasons as Dagster OSS.

---

## LLM extraction: Pydantic models as the trust boundary

### Decision

Claude's JSON response is parsed into Pydantic models (`ExtractedCV`, `WorkExperienceItem`) at the extraction step. Downstream code in the bronze layer consumes the Pydantic object directly via attribute access, not as a dict.

### Alternatives considered

**Raw dict from `json.loads()`**: simplest, no extra dependency. Rejected because every downstream consumer would need to re-implement defensive checks (key presence, type coercion, placeholder detection, deduplication). The same validation logic would drift across files over time.

**Pydantic for validation, then immediate `model_dump()` to dict**: validates once, then passes a plain dict downstream. Rejected because it throws away the type information right after creating it. Attribute access (`cv_data.candidate_name`) catches typos at edit time; dict access (`cv_data["candidate_nmae"]`) only fails at runtime, on the specific CV that happens to exercise that line.

**TypedDict instead of Pydantic**: gives static typing without runtime validation. Rejected because the data crosses a trust boundary (LLM output → our system) where runtime validation is the actual goal. Static types don't catch a hallucinated placeholder name.

### Reasoning

The extraction step is a trust boundary: everything upstream is untrusted (an LLM might hallucinate, return malformed JSON, or invent placeholder values), and everything downstream should be able to assume the data is well-formed. Pydantic enforces that boundary in one place:

- Required fields are guaranteed present after validation passes.
- Placeholder values (`"n/a"`, `"unknown"`, etc.) are rejected at the boundary, not silently propagated to BigQuery.
- Field constraints (max lengths, deduplication of skills) are declared once in `schemas.py` rather than scattered across consumers.

Keeping the Pydantic object alive past the boundary preserves these guarantees throughout the bronze layer. Conversion to dict happens only when crossing another boundary — serializing to JSON for the GCS backup, or building row dicts for `insert_rows_json`.

### Implementation

- `schemas.py` defines `ExtractedCV` and `WorkExperienceItem` with validators for placeholders and skill cleanup.
- `extract_cv_data_with_claude()` returns an `ExtractedCV` instance, not a dict. The function signature is the contract.
- `extract_entities` reads fields via attribute access (`cv_data.candidate_name`, `exp.company_name`).
- Conversions to dict are explicit and happen only at output boundaries:
  - `cv_data.model_dump()` when serializing the full payload to GCS.
  - Hand-built dicts when constructing BigQuery rows, so the BQ column names stay visible in the code.

### Lesson learned

The first integration of this contract had `extract_entities` calling `.get()` on the Pydantic object, which fails with `AttributeError` on every CV. The bug was caught only at materialization time because `test_pydantic_extraction.py` verified extraction in isolation but no test exercised `extract_entities` end-to-end. Two follow-ups:

1. Type-hint the return of `extract_cv_data_with_claude` as `-> ExtractedCV` so editors flag dict-style access immediately.
2. Add an asset-level test that runs `extract_entities` against one CV to catch contract mismatches before materialization.

---

## 5.Error handling: narrow exceptions, let bugs crash

### Decision

Asset code catches only the specific exception types that represent expected, per-record failures (e.g. `ValidationError` for a CV whose extracted data doesn't match the Pydantic schema). All other exceptions — `AttributeError`, `KeyError`, `TypeError`, network errors, BigQuery errors — are allowed to propagate and crash the asset.

### Alternatives considered

**Broad `except Exception`**: catches everything, logs it, continues to the next record. Rejected because it cannot distinguish a per-record problem ("this one CV is malformed") from a systemic problem ("my code has a bug, or the API is down"). The pipeline appears successful while doing nothing useful, and downstream consumers see an empty or partial bronze layer with no signal that anything went wrong.

**No exception handling at all**: any failure aborts the asset. Rejected because legitimate per-record issues (one CV out of 300 has unreadable text, or Claude hallucinated a placeholder name) should not block the other 299 from being processed.

**Broad `except` plus a post-loop sanity check** (e.g. "fail if 0 rows were inserted"): catches the symptom but not the cause. The sanity check fires after burning API quota on every record. Useful as a backstop, not as a substitute for narrow exceptions.

### Reasoning

Failures in this pipeline fall into three categories, and conflating them produces bad outcomes:

1. **Bad input** — one record's data is unusable (CV text is garbled, Claude returns invalid JSON for this specific input). The correct response is *skip and continue*.
2. **Code bug** — the asset's own code is wrong (calling `.get()` on a Pydantic object, referencing a column that doesn't exist, off-by-one indexing). The correct response is *crash immediately so the bug is visible*.
3. **Infrastructure failure** — the API is unreachable, BigQuery is rejecting inserts, credentials expired. The correct response depends on whether it's transient (retry) or persistent (crash); either way, silently continuing produces no useful work.

A broad `except Exception` treats all three the same: log and continue. This is the worst possible default, because it masks bugs (category 2) and outages (category 3) behind a wall of identical-looking log lines, while wasting time and money on operations that cannot succeed.

Narrow exceptions encode the principle that **only category 1 should be tolerated mid-run**. Categories 2 and 3 should produce loud, fast failures that surface in Dagster's UI on the first failing record.

### Implementation

- `extract_entities` catches `pydantic.ValidationError` only. A CV whose Claude response fails schema validation is logged and skipped; everything else propagates.
- BigQuery inserts (`insert_rows_to_bigquery`) are placed outside the per-record `try` block, so insert failures crash the asset rather than being silently swallowed.
- This pattern applies to all future assets: identify the specific exception that represents "this record is bad" and catch only that. If no such category exists for an asset, don't add a `try/except` at all.

### Lesson learned

The original implementation used `except Exception as e` in `extract_entities`. When a code bug (`.get()` on a Pydantic object) caused every CV to fail with `AttributeError`, the asset processed all 300 CVs, logged 300 identical-looking failures, returned `{"work_experience_count": 0, "skills_count": 0}`, and Dagster marked the run successful. The bug was only noticed by reading BigQuery directly and finding empty tables. Narrowing the exception would have crashed the asset on the first CV with the real traceback visible in the Dagster UI.

### Related future decisions

- **Retry strategy for transient infrastructure errors** (tenacity on Claude API calls, BigQuery insert retries). Once retries are in place, the narrow-exception list at the asset level stays small — most infrastructure issues are absorbed inside the lower-level functions.
- **Dead-letter pattern for category-1 failures**. Currently skipped CVs are only visible in logs; a `failed_extractions` table would make them queryable and reviewable.

---

## 6.Bronze schema: one table per asset, joined by submission_id

### Decision

Each bronze table is owned by exactly one Dagster asset. Tables that need data from multiple processing steps are split, with `submission_id` as the shared key for downstream joins.

Current bronze tables:
- `raw_cv_texts` — owned by `extract_raw_text`. PDF metadata, raw text, profile classification.
- `raw_candidates` — owned by `extract_entities`. Contact info extracted by Claude.
- `raw_work_experience` — owned by `extract_entities`. Work history extracted by Claude.
- `raw_skills` — owned by `extract_entities`. Skills extracted by Claude.

### Alternatives considered

**Single `raw_candidates` table containing both PDF-extracted and Claude-extracted columns**: simpler conceptually, fewer tables. Rejected because two assets writing to the same table creates ambiguous ownership: the first asset writes columns it can populate, the second is expected to fill the rest, but nothing enforces this. The original implementation had this shape and silently left contact fields NULL because the second asset wrote nowhere.

**Single asset that does both PDF extraction and Claude extraction**: keeps one table, one writer. Rejected because it conflates two operations with very different costs (PDF parsing is free and fast; Claude calls are expensive and slow) and prevents independent re-materialization (e.g. re-extracting Claude data without re-parsing all PDFs).

### Reasoning

Single-writer-per-table makes the data flow honest: looking at any bronze table, you can point to exactly one asset responsible for its contents. If a column is missing, you know which asset to debug. Idempotency logic lives in one place per table, not split across multiple writers.

The cost is more tables and explicit joins downstream. Silver layer transformations will join `raw_cv_texts` and `raw_candidates` on `submission_id` to produce a unified `silver.candidates` model. That's a routine dbt pattern.

**Heuristic and derived fields stay out of bronze.** The original schema had `seniority_detected` (keyword-based) in bronze. It has been removed: bronze stores extracted data, not derived signals. Seniority will be computed in silver from structured work-experience data, where it can be derived from job titles and years of experience rather than from text keywords.

### Implementation

- `submission_id` is the shared key, derived from the PDF filename.
- `raw_cv_texts` is populated first by `extract_raw_text`.
- `raw_candidates`, `raw_work_experience`, `raw_skills` are populated by `extract_entities`, which depends on `extract_raw_text` in Dagster's asset graph.
- Joins in silver use `INNER JOIN ON submission_id`. A CV that fails Claude extraction (Pydantic validation error) will exist in `raw_cv_texts` but not in the other three; the inner join naturally excludes it from silver, which is correct.

### Lesson learned

The original schema put both raw-text columns and Claude-extracted columns in `raw_candidates`, owned only by `extract_raw_text`. `extract_entities` extracted the contact fields but wrote them only to a GCS backup JSON, never to BigQuery. The bug was invisible until a `SELECT * FROM raw_candidates` showed all contact fields NULL across all rows. The single-writer rule prevents this class of error: if no asset can populate a column, that column doesn't belong in the table.

---

## 7.Profile classification: coarse pre-filter, not accurate classifier

### Decision

The `classify_profile` function in `extract_raw_text` uses keyword matching against a curated list (`TECHNICAL_KEYWORDS`) to decide whether a CV is technical. The threshold is "3 or more keyword matches → technical." Non-technical CVs are skipped in `extract_entities`, avoiding the Claude API cost.

### Reasoning

This is a routing decision, not a classification problem. The cost of a false positive (sending a non-technical CV to Claude) is ~$0.001 per CV. The cost of a false negative (skipping a real technical CV) is that the candidate disappears from the pipeline. False negatives are therefore more harmful than false positives, and the classifier is tuned permissively.

Substring matching is used rather than whole-word matching. For the current synthetic CV set, this is acceptable. The list is curated to cover modern technical vocabulary including cloud platforms (AWS, GCP, Azure), data engineering (dbt, dagster, spark, kafka), BI tooling (power bi, tableau, dax), and AI/ML (langchain, huggingface, embeddings, rag).

### Alternatives considered

**LLM-based classifier**: send each CV to Claude with a short "is this technical?" prompt. Higher accuracy but adds an API call per CV before the main extraction call, doubling the cost and latency.

**Trained ML classifier**: train a model on labeled CVs. Overkill for a routing decision at this scale.

**No classifier**: send every CV to Claude. Acceptable for 300 CVs; not acceptable at production scale.

### Implementation

- `TECHNICAL_KEYWORDS` covers ~130 high-signal keywords across major technical domains.
- Threshold of 3 matches is empirically chosen — high enough to filter out non-technical CVs that mention 1-2 tech words coincidentally, low enough that even minimal-vocabulary technical CVs pass.
- `extract_entities` checks `profile_type == "non_technical"` and skips without calling Claude.

### Known limitations

- **Substring matching false positives**: "react" matches as a verb in non-tech contexts. For the current synthetic CV set this is not a problem; if ingesting real-world CVs, whole-word matching (regex with word boundaries) should be considered.
- **Vocabulary lag**: new tools and roles emerge constantly. The keyword list will need periodic refresh.

### Lesson learned

The initial keyword list lacked BI/analytics vocabulary (power bi, tableau, dax, qlik). A junior BI Analyst CV with only `sql` as a matching keyword was classified as non-technical and silently skipped from Claude extraction. The fix was twofold: expand the keyword list to cover BI tooling, and recognize that the classifier is a permissive pre-filter, not an authoritative classification.

---

## Future decisions to document here

- ~~LLM extraction approach~~ — see "LLM extraction: Pydantic models as the trust boundary" above.
- Company verification dataset (PeopleDataLabs vs BigPicture vs GLEIF vs Companies House).
- Embedding model choice (all-MiniLM-L6-v2 vs alternatives).
- Vector search platform (BigQuery vector search vs pgvector).
- Failure handling depth (dead-letter implementations, retry strategies).
- Observability stack (Looker Studio vs Metabase vs both).

Each decision will be added here as it is made, with the same structure: decision, alternatives considered, reasoning, implementation notes.