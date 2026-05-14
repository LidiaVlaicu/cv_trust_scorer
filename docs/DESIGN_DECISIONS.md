# Design Decisions

A record of significant technical choices in the project, their alternatives, and the reasoning behind them. Updated as new decisions are made.

---

## Authentication: ADC with service account impersonation

### Decision

Local development uses Application Default Credentials with service account impersonation. CI/CD will use Workload Identity Federation (planned in week 5-6).

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

## Data architecture: medallion in BigQuery

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

## Orchestration: Dagster OSS

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

## Transformations: dbt with BigQuery adapter

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

## Future decisions to document here

- LLM extraction approach (Pydantic AI vs direct API calls vs LangChain).
- Company verification dataset (PeopleDataLabs vs BigPicture vs GLEIF vs Companies House).
- Embedding model choice (all-MiniLM-L6-v2 vs alternatives).
- Vector search platform (BigQuery vector search vs pgvector).
- Failure handling depth (dead-letter implementations, retry strategies).
- Observability stack (Looker Studio vs Metabase vs both).

Each decision will be added here as it is made, with the same structure: decision, alternatives considered, reasoning, implementation notes.