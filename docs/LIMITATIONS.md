# Limitations and constraints

What this project does not do, as of today. Each entry says what the limit is
and why, because a limit that follows from a deliberate decision needs a
different sentence in a write-up than one that is simply unfinished.

- **Functional** — what the system cannot tell you
- **Scale and performance** — where it stops working as volume grows
- **Testing** — what is and is not verified
- **Operations** — running it, deploying it, keeping it alive
- **Security and data** — what is exposed and what is not handled
- **External constraints** — limits imposed by other people's systems
- **Evidential** — what the results cannot be claimed to prove

A closing table separates the deliberate from the unfinished.

---

## Functional

### F1. There is no verdict per candidate

The three gold signals are leaf tables. Nothing joins them, so the project's
own question — can this candidate be believed? — is answered in three separate
places and combined by whoever reads them.

*Why:* the rollup was never built. Each signal has a confidence of its own, but
the rule for combining them across signals does not exist.

### F2. Company verification covers UK employers only

Companies House registers UK companies. Since 2026-10-24 every generated
candidate is UK based, which removes most of this exposure — the earlier
dataset placed 159 of 300 candidates abroad, and roughly half its employer rows
were outside the register's reach.

What remains: nothing constrains the *employers* a CV names, so the model can
still place a UK candidate at a foreign company. For those rows `unconfirmed`
means "this register cannot confirm it", not "the company is invented", and the
status vocabulary does not distinguish the two.

### F3. A typo inside a word makes an employer unconfirmed

Matching is tolerant at the word level — case, punctuation, legal suffixes
(`Ltd` / `Limited`), word order, and extra words are all handled, the last as
`partial_match`. What is not handled is a misspelling *within* a word:
`"Ancme Ltd"` against `"Acme Ltd"` is `different`.

*Why:* deliberate, changed on 2026-10-07. The previous version scored
similarity 0–100 with cut-offs at 85 and 60, and neither number could be
defended. Character-level fuzzy matching (`rapidfuzz`) was removed in favour of
a word rule that can be checked by eye. The cost is this case.

### F4. `partial_match` leads nowhere

`"Monzo"` against `"Monzo Bank Limited"` is recorded as `partial_match`.
Nothing consumes it, and no rule says whether it counts for or against a
candidate. It becomes a real question only once F1 exists.

### F5. Seniority is never inferred

A role stating no level is excluded from the responsibility signal, and a
candidate with no levelled role is `not_evaluated` rather than `confirmed`.

*Why:* deliberate. A CV lists only recent jobs, so an honest Senior's first
listed role shows no prior months and would read as junior.

### F6. The seniority-pace check can only fire on E5 and above

The shortfall margin is six years, which exceeds the ladder's own minimum for
Mid (2y) and Senior (4y). In practice it only fires on Staff, Lead, Manager,
Principal and Director claims.

*Why:* deliberate. A CV lists only recent roles, so prior experience read off
one undercounts a real career, worst at the top of the ladder.

### F7. Only two date formats are understood

`"August 2017"` and `"Aug 2017"`, plus five current markers. Anything else —
`01/2020`, `2017–2019`, a season, a year alone — parses to NULL and is flagged.

### F8. Non-technical CVs are skipped entirely

Fewer than three technical keywords and the CV is never extracted.

*Why:* deliberate, to avoid paying for extractions the project cannot use. It
is a permissive pre-filter, not a classifier.

### F9. Bronze's skill categories are computed and never read

`skill_category` is written for every skill; silver derives its own
`normalized_skill` from the reviewed taxonomy and ignores the column.

### F10. Reference data staleness is invisible

The three `dim_` loaders are hand-run scripts, not Dagster assets. Edit a
reviewed CSV, skip the loader, and silver keeps matching the old vocabulary
with no warning.

### F11. There is no interface

Results exist only as BigQuery tables — no API, no dashboard, no report. The
`fastapi`, `uvicorn` and `streamlit` packages sit in `requirements.txt` and
nothing imports them.

### F12. The pipeline runs only when a person runs it

No schedules, no sensors. Every materialization is manual, and nothing notices
a new CV arriving in the bucket.

### F13. One CV, one candidate

Nothing deduplicates. The same person submitting twice is two candidates, and
no rule links them.

### F14. No handling of non-English or unusual CV structures

The keyword list, the date formats, the seniority ladder and the extraction
prompt are all English. A two-column or graphics-heavy CV may extract poorly,
and nothing detects that it did.

---

## Scale and performance

This is the section a reviewer is most likely to probe, because the current
design has a hard ceiling that is easy to state.

### S1. Every table read is loaded fully into memory

There is **no pagination, no streaming and no batching anywhere.** Every
adapter is a variant of:

```python
return [dict(row) for row in self._client.query(query).result()]
```

`get_all_cv_texts()` is the worst case — it selects `raw_text` for every CV and
materializes the lot. At 300 CVs that is a few megabytes. At 100,000 CVs, with
~5 KB of text each, it is about **500 MB in a single Python list** before any
work begins, and silver's full-refresh transforms build a second list beside it.

The process would run out of memory long before correctness became the issue.

### S2. Inserts are one request per table, with no chunking

`insert_rows_to_bigquery` passes every row to `insert_rows_json` in a single
call. BigQuery's streaming insert caps a request at **10 MB**, so a large run
fails outright rather than degrading — and partial success is possible, since
failed rows are reported per row.

### S3. Processing is sequential

One Claude call per CV, one Companies House call per uncached employer, with a
0.5 second pause between them. Nothing runs concurrently.

The left column is measured (see S5); the right is that rate extrapolated, not
an observation:

| | 300 CVs (measured) | 100,000 CVs |
|---|---|---|
| Claude extraction, ~7.8 s/CV | 39 min | **~217 hours** |
| Company lookups, ~900 roles | 14 min | **~78 hours** |
| Cost of one extraction pass | ~$1.70 | **~$570** |

The pipeline is usable at thesis scale and would need redesign — batching,
concurrency, chunked reads — to go beyond roughly a few thousand CVs.

### S4. Full refresh re-does all work every run

Silver and gold truncate and reload. That is correct and cheap at 300 rows; at
scale it means recomputing every candidate to add one.

Bronze is the exception — content hashes skip unchanged CVs, which is the only
incremental path in the project.

### S5. Timings are recorded, nothing else is

Every asset returns `duration_seconds`, visible in its Dagster materialization
metadata. A full run of 300 CVs on 2026-10-25:

| Asset | Duration |
|---|---|
| `extract_raw_text` | 5 min 50 s |
| `extract_entities` | 38 min 54 s |
| the three silver assets | 8 s |
| the two date and responsibility signals | 6 s |
| `verify_companies` | 14 min 10 s |
| **total** | **~59 min** |

What is still missing: no profiling, no memory measurement, no benchmark at any
other volume, so the 100,000-CV column above remains arithmetic rather than an
observation.

One timing is worth reading twice: a re-run where every CV hashes unchanged
still takes 51 seconds, because the hash is computed on bytes that must be
downloaded first. Skipping avoids reprocessing, not transfer.

### S6. Runtime is not bounded

A long CV could produce JSON exceeding the 2,000-token output cap, which would
truncate the response and fail validation. Nothing detects or retries that case,
and no asset has a timeout.

---

## Testing

### T1. 626 tests, and all of them are in-process

Two kinds only: unit tests over pure functions, and whole-asset tests driven
against in-memory fakes. Both are fast and free, and both stop at the process
boundary.

### T2. No integration tests

Nothing exercises real BigQuery, real GCS, a real Claude call, or the real
Companies House API. Every adapter — the code that actually writes the SQL and
builds the rows — is the one part the suite never runs.

### T3. The fakes can drift from the real adapters

A fake implements the same protocol by hand. Nothing checks that
`BigQuerySkillsWarehouse` and `FakeSkillsWarehouse` behave alike, so a fake can
keep passing after the real adapter's query changes. There are no contract
tests.

### T4. The schemas are not checked against the live tables

The four bronze schemas were compared against BigQuery once, by hand. No test
reads the live schema, so a column added in the console would go unnoticed.

### T5. No end-to-end test of the DAG

Nothing materializes the eight assets in order, even against fakes. Dagster
loading successfully is the only assurance that the graph is wired correctly.

### T6. The PDF round trip is untested

Rendering a CV to PDF and reading it back with PyMuPDF has no coverage — and it
is the pipeline's actual input. Section headings are detected by being short and
uppercase, a convention shared between two files with nothing asserting they
still agree.

### T7. Gaps in unit coverage

`classify_profile` — the three-keyword rule that decides what the project spends
money extracting — has no direct test; it is exercised only through the asset.
The error paths inside the BigQuery adapters are untested.

### T8. No coverage measurement, no load tests, no property-based tests

Coverage has never been measured, so "626 tests" says nothing about what
fraction of branches run. There are no performance tests, no load tests, no
fuzzing of the CV text, and no mutation testing to check the tests would notice
a broken rule.

### T9. CI runs the suite, and nothing more

`.github/workflows/ci.yml` installs the project on a clean Ubuntu runner and
runs ruff, black, isort and pytest on every pull request. It completes in about
a minute, rising to roughly four and a half when the dependency cache is
rebuilt; the tests themselves are 5 seconds of that.

No credentials are configured there, deliberately, so anything reaching GCS,
BigQuery or an API fails rather than passing quietly against the real project.
The consequence is that CI inherits T2 exactly: it proves the project installs
and that the in-process tests pass, and nothing about the adapters.

---

## Operations

### O1. The install is declared twice

`anthropic` and `python-dotenv` were missing from `requirements.txt`, and ten
packages were listed that nothing imports, including `torch`, `transformers`
and `spacy`. Both are fixed, and CI installs the project on a clean runner on
every pull request, so a broken dependency list now fails there rather than
silently.

What remains is duplication: dependencies are declared in both `pyproject.toml`
and `requirements.txt`, CI installs from the first and the README tells a reader
to use the second. Nothing keeps the two in step.

### O2. Only bronze is checked

Four asset checks run against the bronze tables. Silver and gold have none — no
check that silver is row-for-row with bronze, and no duplicate check on the
gold signals, one of which is append-only.

### O3. Failures are retried only by re-running, and nothing records them

Error handling itself is deliberate and works: the three assets that touch the
outside world catch per row and continue, so one bad PDF cannot stop the other
313. Because each asset skips what it has already processed, a failed CV is
picked up automatically the next time the asset runs — that is the retry
mechanism, and it is idempotent by design.

Four things are missing around it:

- **No retry within a run.** A transient 503 loses that row until the next run.
- **No record of what failed.** The only trace is a `[FAIL]` line in Dagster's
  run log — no dead-letter table, no failure column, nothing queryable.
- **The run reports success regardless.** Neither asset returns a failure
  count, no asset check looks for one, and nothing alerts. Fifty failures and
  264 successes looks like a clean run.
- **No distinction between transient and permanent.** A CV that will never
  extract is retried on every run, paying for a Claude call each time, with
  nothing marking it as abandoned. This is the one that costs money rather
  than visibility.

### O4. No monitoring or alerting

No metrics, no logs beyond Dagster's own run output, no notification when a run
fails or a check warns. Finding out requires looking.

### O5. One environment

A single GCP project and three datasets. No dev/prod separation, so there is
nowhere to run the pipeline for real without writing to the only copy of the
data.

### O6. No deployment, and it has only ever run on one machine

Developed and run on macOS, Python 3.11, locally. No Dockerfile, no container,
no Linux run, no cloud deployment. Dagster is started by hand with
`DAGSTER_HOME` pointing at a local folder.

### O7. No cost guard

A full extraction pass costs roughly **$1.70** at Haiku 4.5 rates. Nothing caps
spend, counts calls in advance, or warns before a large run. The protection is
incidental — content hashes and the search cache.

The failure mode is real: a config change once shifted the filenames the fixed
seed produces, so a run that should have skipped everything generated 14
unplanned CVs.

### O8. Two asset names do not match their filenames

`extract_cv_text.py` defines `extract_raw_text`; `signal_company_verification.py`
defines `verify_companies`. Cosmetic, but renaming a live Dagster asset loses its
materialization history, so it stays.

---

## Security and data

### D1. Secrets live in one `.env` file

Seven variables including two API keys. No secret manager, no rotation
procedure, and rotation is a manual edit. `.env` is correctly gitignored.

### D2. No access control is documented

Nothing in the repo states who can read the datasets or what the service
account is permitted to do. Authentication uses impersonation, which is sound,
but authorization is undescribed.

### D3. No personal data handling, because the data is synthetic

The CVs are generated, so no GDPR position, retention policy, anonymization
step or deletion path exists. Pointing this pipeline at real CVs would require
all of it — names, emails and phone numbers are stored in clear text in bronze
and silver.

### D4. No audit trail of who ran what

Dagster records materializations locally. Nothing records which person ran a
pipeline or edited a reviewed CSV beyond git history.

---

## External constraints

Limits set by other systems, not choices in this codebase.

| Source | Constraint | Where it bites |
|---|---|---|
| Companies House | UK register only | F2 — half the roles are out of scope |
| Companies House | public API rate limit (~600 requests / 5 min) | the 0.5 s pause sits near that ceiling; at scale this is the slowest path |
| Claude Haiku 4.5 | 200K context, and the code caps output at 2,000 tokens | S6 — a long CV can truncate its own JSON |
| Claude API | priced per token | O7 — cost scales linearly with CVs, no batching discount used |
| BigQuery | 10 MB per streaming insert request | S2 — a large insert fails rather than slowing |
| BigQuery | streaming inserts are not immediately consistent for some operations | not currently handled or tested |
| PyMuPDF | can only recover text a PDF actually contains | a scanned or image-only CV yields nothing, and T6 means this is untested |
| GitHub Actions | 2,000 free minutes/month on private repos | not a constraint — a run takes about a minute |

---

## Evidential

Limits on what the results can be claimed to show. These matter most for the
write-up.

### E1. The CVs are synthetic

300 CVs from one model and one prompt template. Real CVs vary more in layout,
length and language, and real fabrication is unlikely to resemble fabrication a
model was asked to produce.

### E2. The labels record intent, not verified fact

A CV in `data/inconsistent/` was *asked* to contain a flaw. Nothing checks that
the model complied — the generation code says so explicitly. Every figure
measured against those folders inherits that uncertainty.

### E3. One flaw type cannot apply to every CV that carries its label

`tech_anachronism` quoted wrong release years until 2026-10-24: dbt was given as
2019 against its real 2016 release, so a CV claiming dbt in a 2017 role carried
no anachronism at all. The years are now the real ones.

What the fix cannot repair: the flaw needs a role that ended at least two years
before the technology existed, and **5 of the 29 CVs carrying this label declare
one or two years of experience**, so no role of theirs is old enough. Report
this type against 24 achievable cases, not 29.

### E4. Thresholds were tuned and scored on the same data

No hold-out split, so figures measured on the set the thresholds were chosen
against cannot be reported as generalising.

### E5. Signal accuracy is not currently reproducible

The precision and recall harnesses were removed while the measurement is
deferred. The `proven` / `suggestive` labels driving every confidence value came
from figures no code in the repo regenerates.
`SENIORITY_SHORTFALL_FLAG_MONTHS = 72` is the one threshold whose value was
chosen *by* that measurement, so it is the least defensible from the repository
alone.

### E6. The dataset is English and UK-based

One language, and since 2026-10-24 every candidate is based in one of ten UK
cities — chosen so Companies House can verify the employers (F2). Nothing
establishes behaviour outside that, and the earlier European spread is no
longer represented.

### E7. No baseline and no comparison

Nothing measures this approach against an alternative — a simpler heuristic, a
single LLM prompt asked to judge the whole CV, or a human reviewer. There is no
evidence that the layered pipeline outperforms a simpler method.

---

## Deliberate, or unfinished?

| Deliberate — defensible as designed | Unfinished — would be fixed given time |
|---|---|
| F3 word comparison over a tuned score | F1 no per-candidate verdict |
| F5 seniority never inferred | F2 single register, no "not checkable" status |
| F6 six-year margin, E5+ only | F4 `partial_match` consumed by nothing |
| F8 permissive technical pre-filter | F10 reference staleness invisible |
| F9 bronze records, silver supersedes | O1 two declarations of the install |
| O3 per-row failure, the run continues | T3 no contract tests for the fakes |
| S4 full refresh at this scale | T2 no integration tests |
| D3 synthetic data, so no PII exposure | T6 PDF round trip untested |
| E1 synthetic data for labelled evaluation | E5 accuracy not reproducible |
| T9 CI proves the install and the suite | S1–S3 no path beyond a few thousand CVs |

The left column is the architecture working as intended. The right column is
the backlog — and E5 is the one that most affects whether someone else can
trust the result.
