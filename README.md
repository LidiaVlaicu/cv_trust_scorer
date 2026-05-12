# CV Trust Scorer

A data engineering pipeline that ingests technical CVs as PDFs, extracts structured information, cross-references against external data sources, and computes inconsistency signals for human review.

> **Status**: in active development. Master's TFM project, September 2026 defense.

## What it does

The pipeline processes IT-focused CVs through five stages:

1. **Ingestion**: PDFs uploaded to GCS, raw text extracted with PyMuPDF.
2. **Structured extraction**: LLM-based extraction produces validated JSON (work experience, skills, education, dates).
3. **Normalization**: dbt transformations in BigQuery clean and structure the data.
4. **Signal computation**: five inconsistency signals are computed per CV (company verification, date overlap, technology anachronism, career coherence, skills mismatch).
5. **Reporting**: consolidated report exposed via FastAPI.

The system surfaces inconsistencies for human review. It does not make hiring decisions.

## Architecture

- **Storage**: Google Cloud Storage (raw PDFs), BigQuery (medallion architecture: bronze, silver, gold).
- **Orchestration**: Dagster OSS (self-hosted).
- **Transformations**: dbt with BigQuery adapter.
- **Extraction**: PyMuPDF for PDF text, Pydantic AI for LLM-based structured extraction.
- **Verification**: sentence-transformers embeddings, BigQuery vector search.
- **Validation**: Pydantic schemas at every layer boundary.
- **Infrastructure**: Terraform (planned), Docker for local development, GitHub Actions for CI/CD.

## Authentication

This project uses Application Default Credentials with service account impersonation for local development. The pipeline runs as a dedicated service account (`cv-trust-scorer-runner`) with scoped IAM roles. No long-lived JSON keys are stored on disk.

For setup instructions, see [docs/SETUP.md](docs/SETUP.md).
For the reasoning behind this choice, see [docs/DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md).

## Getting started

```bash
git clone https://github.com/YOUR_USERNAME/cv-trust_scorer.git
cd cv-trust_scorer
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your project values
```

Then follow [docs/SETUP.md](docs/SETUP.md) for authentication and GCP setup.

Verify the setup:

```bash
python scripts/test_auth.py
```

## Project structure

```
cv-trust_scorer/
├── api/                # FastAPI service (planned)
├── app/                # Streamlit UI (planned)
├── dagster/            # Dagster pipeline definitions
├── data/               # Synthetic CVs (legitimate and inconsistent)
├── dbt/                # dbt transformations
├── docs/               # Project documentation
├── ingestion/          # Ingestion scripts
├── scripts/            # Utility scripts (setup, verification)
├── tests/              # Python tests
├── .env.example        # Template for environment variables
├── .gitignore
├── README.md
└── requirements.txt
```

## Documentation

- [SETUP.md](docs/SETUP.md): step-by-step setup instructions.
- [DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md): rationale for significant choices.
- [TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md): solutions to known issues.
- [SCALING.md](docs/SCALING.md): how the architecture would change at production scale (planned).
- [LIMITATIONS.md](docs/LIMITATIONS.md): known gaps and tradeoffs (planned).

## Status and roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md) for the week-by-week build plan.

## License

This is a master's thesis project. Code is provided for educational and review purposes.