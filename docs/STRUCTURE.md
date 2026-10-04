# Project structure

The project is organised on two axes:

- **top level is the medallion layer** — `bronze/`, `silver/`, `gold/`
- **inside each layer, `rules/` is pure and `assets/` does the I/O**

So a path tells you both what stage of the pipeline you are in and whether the
code touches the outside world. `silver/rules/work_experience.py` is pure date
and string logic; `silver/assets/silver_work_experience.py` is the BigQuery
adapter and the Dagster asset that feeds it.

Bronze adds a third folder, `bronze/io/`, because it is the only layer that
talks to three outside systems — GCS, BigQuery and Claude. Silver and gold
reach BigQuery through the `shared/` package instead.

## The layers

| Layer | Question it answers | Row shape |
|---|---|---|
| `bronze/` | What did we receive? | raw, append-only, never corrected |
| `silver/` | What does it say, in a consistent form? | row-for-row with bronze |
| `gold/` | Can we believe it? | one row per candidate, a verdict |
| `reference/` | What do we compare against? | small, human-reviewed, in git |

The row-shape column is the test to apply when you are unsure where new code
belongs. If it turns one row into one row, it is silver. If it reads a
candidate's whole history and emits a judgment, it is gold.

```
bronze/                     LAND IT. Store what arrived; interpret nothing.
  rules/cv_analysis.py        pure classifiers over CV text
  schemas.py                  the ExtractedCV validation contract
  io/gcs_storage.py           GCS: read the PDFs, archive the raw JSON
  io/bigquery_persistence.py  BigQuery, including change detection
  io/llm_extraction.py        the Claude call
  assets/extract_cv_text.py   GCS PDFs -> raw_cv_texts
  assets/extract_entities.py  raw_cv_texts -> the three entity tables
  assets/check_assets.py      bronze data-quality checks (Dagster asset checks)

silver/                     CLEAN IT. Standardize and validate.
  rules/candidates.py                 name, phone (E.164), email
  rules/skills.py                     taxonomy matching
  rules/work_experience.py            titles, CV months, locations
  assets/silver_candidates.py         one adapter + Dagster asset per entity
  assets/silver_skills.py
  assets/silver_work_experience.py

gold/                       JUDGE IT. Trust signals.
  rules/timeline_consistency.py            thresholds and date arithmetic
  rules/responsibility_mismatch.py         extraction patterns and the rules
  assets/signal_timeline_consistency.py    adapters + Dagster assets
  assets/signal_responsibility_mismatch.py
  assets/signal_company_verification.py    Companies House check

reference/                  Human-reviewed inputs; the dim_ tables.
  seniority_ladder.py                   the published engineering ladder, cited
  reviewed/                             the 3 CSVs a person edits
  parsing/common/reference_csv.py       read a CSV into checked rows
  parsing/dim_job_titles.py             job_title -> seniority_level
  parsing/dim_location_aliases.py       location_token -> country
  parsing/dim_skills.py                 alias -> canonical_skill (one row, many)
  loaders/load_dim_job_titles.py        rows -> BigQuery, full refresh
  loaders/load_dim_location_aliases.py
  loaders/load_dim_skills.py

shared/                     BigQuery plumbing for silver, gold and reference
  bigquery_client.py          bigquery_client, dataset_name
  bigquery_tables.py          table_id, replace_table

external/companies_house/   Third-party API client
dataset_generation/         How the dataset was made
pipeline/definitions.py     Dagster wiring, and nothing else
tools/                      Run by hand: setup checks and probes (see its README)
tests/                      Mirrors the tree above
```

## The rule that is actually enforced

`tests/test_architecture.py` reads the import statements of every module under
a `rules/` folder and fails if one imports BigQuery, Dagster, an API
client, or even `os`:

```
AssertionError: silver/rules/skills.py imports ['google.cloud'].
Pure rules must stay I/O-free - move that part into the assets/ shell.
```

This is why the whole suite runs in about a second with no credentials and no
mocking, and it is what lets the thesis claim a pure-core architecture as a
property of the codebase rather than an intention.

It also enforces direction: `assets/` imports `rules/`, never the reverse.

## Running things

```bash
# reference data first — the silver assets read the dim_ tables
python -m reference.loaders.load_dim_skills
python -m reference.loaders.load_dim_job_titles
python -m reference.loaders.load_dim_location_aliases

# the pipeline
DAGSTER_HOME="$(pwd)/dagster_home" dagster asset materialize \
  -m pipeline.definitions --select silver_candidates,silver_skills,...

pytest
```

## Known inconsistencies

One thing is deliberately left as it is:

- `gold/assets/signal_company_verification.py` reads bronze directly rather than
  silver, unlike the other two signals, and has no `rules/` half — its pure
  logic lives in `external/companies_house/matching.py` instead.

Every asset now follows the same shape: a pure core, a protocol naming the
reads and writes, the real adapter, and a `run_*()` whose dependencies are
injected. So each one is covered by a fake-store test that needs no GCS, no
BigQuery and no API calls.
