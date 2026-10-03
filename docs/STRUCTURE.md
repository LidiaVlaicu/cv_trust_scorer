# Project structure

The project is organised on two axes:

- **top level is the medallion layer** — `bronze/`, `silver/`, `gold/`
- **inside each layer, `rules/` is pure and `assets/` does the I/O**

So a path tells you both what stage of the pipeline you are in and whether the
code touches the outside world. `silver/rules/work_experience.py` is pure date
and string logic; `silver/assets/work_experience.py` is the BigQuery adapter
and the Dagster asset that feeds it.

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
  rules/parsing.py            pure classifiers over CV text
  schemas.py                  the ExtractedCV validation contract
  llm_extraction.py           the Claude call (I/O, so outside rules/)
  storage.py                  GCS: read the PDFs, archive the raw JSON
  warehouse.py                BigQuery, including change detection
  assets/cv_text.py           GCS PDFs -> raw_cv_texts
  assets/entities.py          raw_cv_texts -> the three entity tables
  assets/quality.py           bronze data-quality checks

silver/                     CLEAN IT. Standardize and validate.
  rules/candidates.py         name, phone (E.164), email
  rules/skills.py             taxonomy matching
  rules/work_experience.py    titles, CV months, locations
  assets/*.py                 one adapter + Dagster asset per entity

gold/                       JUDGE IT. Trust signals.
  rules/timeline_consistency.py        thresholds and date arithmetic
  rules/responsibility_mismatch.py     extraction patterns and the rules
  assets/*.py                          adapters + Dagster assets
  assets/company_verification.py       Companies House check

reference/                  Human-reviewed inputs; the dim_ tables.
  seniority_ladder.py         the published engineering ladder, cited
  reviewed/                   the CSVs a person edits
  parsing/                    pure parsers, with validation
  loaders/                    thin I/O shells, one per dim_ table

warehouse/                  Shared BigQuery plumbing (client, dataset, load)
external/companies_house/   Third-party API client
evaluation/                 Precision/recall harnesses, one per signal
dataset/                    How the thesis corpus was made
pipeline/definitions.py     Dagster wiring, and nothing else
tools/                      Run by hand: setup checks and probes (see its README)
tests/                      Mirrors the tree above
```

## The rule that is actually enforced

`tests/test_architecture.py` reads the import statements of every module under
a `rules/` folder and fails if one imports the warehouse, Dagster, an API
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
python -m reference.loaders.dim_skills
python -m reference.loaders.dim_job_titles
python -m reference.loaders.dim_location_aliases

# the pipeline
DAGSTER_HOME="$(pwd)/dagster_home" dagster asset materialize \
  -m pipeline.definitions --select silver_candidates,silver_skills,...

# how well each signal performs against the folder ground truth
python -m evaluation.timeline_consistency
python -m evaluation.responsibility_mismatch

pytest
```

## Known inconsistencies

Two things are deliberately left as they are, so that a restructure stayed a
restructure:

- `gold/assets/company_verification.py` reads bronze directly rather than
  silver, unlike the other two signals, and has no `rules/` half.
- `silver/assets/candidates.py` predates the warehouse-Protocol pattern the
  other assets use, so it has no injectable adapter and is not covered by
  fake-warehouse tests.
