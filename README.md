# CV Trust Scorer

A data engineering pipeline that ingests technical CVs as PDFs, extracts
structured information, cross-references employers against a public register,
and computes inconsistency signals for human review.

> **Status**: feature complete for the write-up. Master's TFM project,
> September 2026 defense.

## What it does

Four stages run, over a dataset of 300 synthetic CVs:

1. **Ingestion**: PDFs are listed from GCS, hashed to detect changes, and read
   with PyMuPDF into `bronze.raw_cv_texts`.
2. **Structured extraction**: each CV's text goes to Claude, and the response is
   validated against a Pydantic model before it reaches the warehouse. It lands
   as candidates, work experience and skills, worded exactly as the CV wrote it.
3. **Normalization**: silver parses dates, standardizes job titles, splits
   locations and resolves skills and seniority against human-reviewed reference
   tables. Nothing is guessed — an unmatched value is reported.
4. **Signal computation**: three signals, one row per candidate each.

| Signal | Question |
|---|---|
| Timeline consistency | is this employment timeline internally possible? |
| Responsibility mismatch | do the responsibilities claimed contradict the job title? |
| Company verification | can the employer be found in Companies House? |

Each signal reports findings and a confidence, never a score. See
[docs/SIGNALS.md](docs/SIGNALS.md) for how to read them.

A fifth stage — a report or interface over the results — is **not built**.
Results exist as BigQuery tables only.

The system surfaces inconsistencies for human review. It does not make hiring
decisions.

## Architecture

- **Storage**: Google Cloud Storage (raw PDFs and extraction archives),
  BigQuery (medallion architecture: bronze, silver, gold).
- **Orchestration**: Dagster OSS, run locally. Eight assets and four asset
  checks; no schedules or sensors.
- **Transformations**: Python. Every layer has a pure `rules/` module and an
  `assets/` shell that does the I/O, and a test enforces the split.
- **Extraction**: PyMuPDF for PDF text, the Anthropic API (Claude Haiku 4.5)
  for structured extraction.
- **Verification**: the Companies House API, with word-level name comparison
  and a BigQuery cache of every response.
- **Validation**: Pydantic schemas at the extraction boundary, BigQuery schemas
  at every table, Dagster asset checks on the bronze tables.
- **CI**: GitHub Actions runs ruff, black, isort and the test suite on every
  pull request.

Not present, and sometimes expected: no dbt, no embeddings or vector search, no
Terraform, no Dockerfile, no deployment. See
[docs/LIMITATIONS.md](docs/LIMITATIONS.md).

## The dataset

300 synthetic CVs generated with Claude, half carrying planted inconsistencies
and half not. Every candidate is UK based so the employer register applies.
`data/ground_truth.csv` records what each CV was asked to contain, written as
each CV was generated.

The labels record intent, not verified fact: nothing checks that the model
complied, which bounds every figure measured against them.

## Authentication

This project uses Application Default Credentials with service account
impersonation for local development. The pipeline runs as a dedicated service
account (`cv-trust-scorer-runner`) with scoped IAM roles. No long-lived JSON
keys are stored on disk.

For setup instructions, see [docs/SETUP.md](docs/SETUP.md).
For the reasoning behind this choice, see
[docs/DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md).

## Getting started

```bash
git clone https://github.com/LidiaVlaicu/cv_trust_scorer.git
cd cv_trust_scorer
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Edit .env with your project values
```

Then follow [docs/SETUP.md](docs/SETUP.md) for authentication and GCP setup.

Verify the setup:

```bash
python tools/check_gcp_auth.py
```

Load the reference data, then run the pipeline:

```bash
python -m reference.loaders.load_dim_skills
python -m reference.loaders.load_dim_job_titles
python -m reference.loaders.load_dim_location_aliases

DAGSTER_HOME="$(pwd)/dagster_home" dagster dev -m pipeline.definitions
```

## Project structure

The top level is the medallion layer; inside each layer `rules/` is pure
logic and `assets/` does the I/O.

```
cv_trust_scorer/
├── bronze/             Land it: PDFs and LLM extraction -> raw_* tables
├── silver/             Clean it: standardize and validate, row for row
├── gold/               Judge it: the trust signals, one verdict per candidate
├── reference/          Human-reviewed taxonomies and the seniority ladder
├── shared/             Shared BigQuery plumbing
├── external/           Third-party APIs (Companies House)
├── dataset_generation/ How the synthetic CV set was generated
├── pipeline/           Dagster wiring
├── tools/              Run by hand: setup checks and probes
├── tests/              Mirrors the tree above
├── docs/               Project documentation
└── data/               The 300 CVs and their ground truth labels
```

See [docs/STRUCTURE.md](docs/STRUCTURE.md) for what belongs where, and for the
test that enforces the pure/I-O split rather than leaving it to convention.

## Documentation

- [STRUCTURE.md](docs/STRUCTURE.md): the layout, and the architectural rule the tests enforce.
- [SETUP.md](docs/SETUP.md): step-by-step setup instructions.
- [DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md): rationale for significant choices.
- [BUSINESS_RULES.md](docs/BUSINESS_RULES.md): every rule the pipeline applies, and which layer owns it.
- [SIGNALS.md](docs/SIGNALS.md): how to read what the gold signals produce.
- [LIMITATIONS.md](docs/LIMITATIONS.md): what the project does not do — functional, scale, testing, operational.
- [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md): solutions to known issues.
- [tools/README.md](tools/README.md): the by-hand utilities, and why they are not tests.

## License

This is a master's thesis project. Code is provided for educational and review
purposes.
