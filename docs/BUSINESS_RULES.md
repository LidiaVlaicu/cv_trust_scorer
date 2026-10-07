# Business rules

Every rule the pipeline applies, and which layer owns it.

A rule is here if it decides something about a CV: what counts as technical,
what a date means, when a claim contradicts a title. Plumbing is not here.

Each layer may only make the kind of decision its question allows:

| Layer | Question | May decide |
|---|---|---|
| `bronze/` | What did we receive? | whether a CV is worth extracting, and whether the extraction is usable |
| `silver/` | What does it say? | what a value means in a standard form, and whether it is valid |
| `gold/` | Can we believe it? | whether claims contradict each other |
| `reference/` | What do we compare against? | the vocabularies and the ladder |

The hard line: **bronze never corrects, silver never judges.** A CV claiming
40 years at one company is stored verbatim by bronze, parsed into dates by
silver, and only questioned by gold.

---

## Bronze — what did we receive?

### B1. A CV is technical if it contains 3 or more technical keywords

`bronze/rules/cv_analysis.py` → `classify_profile()`

Non-technical CVs are skipped before the Claude call, so this rule decides
what the project spends money extracting.

Three is a deliberate floor: one or two tech words appear by chance in
non-technical CVs (a recruiter who mentions "python"), while a genuine
technical CV names a role, a language and a tool at minimum.

This is a **permissive pre-filter, not a classifier**. Being wrong in the
direction of "technical" costs one extraction; being wrong the other way
silently drops a real candidate. See DESIGN_DECISIONS §7.

### B2. A skill belongs to one of ten categories, or to "other"

`bronze/rules/cv_analysis.py` → `categorize_skill()`

Categories: `language`, `cloud`, `database`, `data_engineering`,
`bi_analytics`, `ml_ai`, `devops`, `web`, `practices`, `other`.

Matching is on the lowercased, stripped name. `"other"` is a legitimate
answer, not a bug — the vocabulary of skills is open, and bronze does not
guess. Normalization against the reviewed taxonomy happens in silver.

### B3. A CV is the same CV if its content hash is unchanged

`bronze/rules/cv_analysis.py` → `compute_file_hash()`,
`bronze/assets/extract_cv_text.py` → `decide_action()`

SHA-256 of the PDF bytes, with three outcomes:

| Outcome | Action |
|---|---|
| hash absent | process it |
| hash matches | skip — nothing has changed |
| hash differs | delete every bronze row for that CV, then reprocess |

The delete-first rule is what stops an edited CV from accumulating two sets
of rows. This is why re-running bronze costs nothing in Claude calls.

### B4. An extraction must have a name, and every role a title and employer

`bronze/schemas.py` → `ExtractedCV`, `WorkExperienceItem`

Required, minimum one character: `candidate_name`, `job_title`,
`company_name`. Optional and allowed to be empty: email, phone, linkedin,
github, website, location, dates, description.

Rejected outright as placeholder values: `n/a`, `none`, `unknown`, `tbd`,
`xxx`, `placeholder` — and for a name, also `candidate` and `name`. These are
what an LLM returns when it has nothing; storing them would create rows that
look populated and are not.

Field lengths are capped (titles 200, descriptions 10,000, at most 200
skills) so a malformed response cannot land an unbounded value.

Skills are deduplicated case-insensitively, keeping the first spelling seen.

### B5. A CV with no readable text is not stored

`bronze/assets/extract_cv_text.py` → `run_extract_raw_text()`

An empty or whitespace-only text extraction is skipped and reported, not
written as an empty row. A row with no text cannot be extracted from and
would fail every downstream check.

### B6. Bronze rows must be usable, not plausible

`bronze/assets/check_assets.py`

Four asset checks. The distinction matters: these ask whether rows *can be
used*, never whether a value is believable.

| Check | Severity | Rule |
|---|---|---|
| ids present and unique | ERROR, blocking | a blank or duplicated id breaks every join |
| every entity row has a matching CV | ERROR, blocking | a row belonging to no CV vanishes from joins |
| required content present | WARN | one bad extraction is worth seeing, not worth stopping for |
| every CV produced entities | WARN | zero jobs *and* zero skills means the LLM returned nothing usable |

Blocking means silver never consumes broken bronze.

---

## Silver — what does it say?

### S1. A CV date is a month and a year, never a day

`silver/rules/work_experience.py` → `parse_cv_month()`

Accepted: `"August 2017"` and `"Aug 2017"`. The day is **always the 1st**,
because a CV states month precision and choosing any other day would invent
information the source does not contain.

### S2. "Present" means the role is current, not a date

`silver/rules/work_experience.py` → `_CURRENT_MARKERS`

`present`, `current`, `now`, `ongoing`, `to date` → `end_date` is NULL and
`is_current` is true. Only "Present" appears in the data; the rest are
variants a future extraction could produce, and reading them as dates would
be worse than recognising them.

### S3. An unparseable date is flagged, not dropped

`silver/rules/work_experience.py` → `work_experience_date_problems()`

The row survives with a NULL date and a problem label. Four labels:

- `unparsed_start_date` / `unparsed_end_date` — did not parse
- `start_after_end` — the range runs backwards
- `date_in_future` — later than today
- `implausible_year` — before 1950 (`EARLIEST_PLAUSIBLE_YEAR`)

These are **validity** checks, not plausibility. Whether the dates fit the
claimed responsibilities is a gold question.

### S4. A job title is reduced to words and single spaces

`silver/rules/work_experience.py` → `standardize_job_title()`

Every character that is not a letter, digit or space becomes a space.
`"Staff Engineer - Cloud Infrastructure"` → `"Staff Engineer Cloud
Infrastructure"`. Written as "keep word characters" rather than as a list of
punctuation to strip, so a separator that has not appeared yet is handled too.

### S5. Seniority comes from the reviewed table, never from the title text

`silver/rules/work_experience.py` → `WorkExperienceReference`

A lookup against `dim_job_titles`. A title absent from the reviewed CSV, or
one stating no level, carries **no seniority** — absence is the answer, not a
guess. Two reviewed rows claiming the same title with different levels raise
an error rather than resolving to whichever was read last.

### S6. A location resolves to a country through the reviewed aliases

`silver/rules/work_experience.py`

`location_token` is the last comma-separated part of the location string.
`UK`, `Scotland`, `Northern Ireland` → United Kingdom; `Stockholm` → Sweden.
Cities are parsed from the string rather than listed, so a new city needs no
reviewed change — only a new country does.

`"Remote"` sets `is_remote` and is stripped as a prefix (`"Remote /
Edinburgh"` is Edinburgh, remote). `"Stockholm Office"` is the same city as
`"Stockholm"`.

### S7. A skill is normalized only if a reviewed alias matches

`silver/rules/skills.py`

No guessing and no keyword heuristic. A skill either matches an alias in
`dim_skills` or `normalized_skill` is NULL and the row is reported as
unmatched for a human to add to the CSV. The raw skill is always kept
alongside, for traceability.

### S8. A phone number is E.164 or NULL

`silver/rules/candidates.py` → `standardize_phone()`

Numbers carrying a country code are parsed with it; numbers without one are
assumed to be `GB` (`_DEFAULT_REGION`). Anything that is not a valid,
assignable number for its country becomes NULL.

### S9. An email is kept as written, with a validity flag

`silver/rules/candidates.py` → `is_valid_email()`

Must contain `@`, a domain with a dot, no spaces, and match the pattern.
Invalid emails are **flagged, not dropped** — `is_email_valid` is false and
the value stays, because the original is evidence.

### S10. A name is uppercased and whitespace-collapsed

`silver/rules/candidates.py` → `standardize_name()`

### S11. Silver is rebuilt from bronze on every run

`silver/assets/*.py`

Full refresh, never an incremental merge. Bronze is the source of truth, so
an incremental load would leave rows from an earlier version of a CV behind.

---

## Gold — can we believe it?

Both signals report findings with an evidence strength, never a score. See
DESIGN_DECISIONS §8 for why, and for the rollup rule.

### G1. Two roles overlapping by more than one month ran at once

`gold/rules/timeline_consistency.py` → `OVERLAP_TOLERANCE_MONTHS = 1`

When one role ends and the next starts in the same month they share a single
transition month, and month precision cannot tell a handover from a genuine
overlap. Two or more months cannot be explained that way.

Three findings by size: `employment_overlap_minor` (suggestive),
`employment_overlap` and `employment_overlap_severe` (both proven).

### G2. A gap of 6 months is notable, 12 is long

`gold/rules/timeline_consistency.py` → `GAP_FLAG_MONTHS = 6`,
`LONG_GAP_FLAG_MONTHS = 12`

Real careers contain gaps — study, parental leave, job hunting — so these are
defensible real-world values rather than numbers tuned to separate a dataset.

### G3. A level claimed more than 6 years early is implausible

`gold/rules/timeline_consistency.py` → `SENIORITY_SHORTFALL_FLAG_MONTHS = 72`

Measured against the ladder's minimum for the claimed level
(`reference/seniority_ladder.py`).

The six-year margin exists because **a CV lists only its most recent roles**,
so prior experience read off one undercounts a real career — and undercounts
it worst at the top of the ladder, where more of the career is missing from
the page. A legitimate Principal showing three jobs presents ~5 years against
the ladder's 11, through no fault of their own.

A consequence worth stating: six years is larger than the ladder's own
minimum for Mid (2y) and Senior (4y), so this check can only ever fire on E5+
claims — Staff, Lead, Manager, Principal, Director. A prematurely claimed
"Senior" is beyond what CV dates can evidence, and is left to G4.

### G4. More than one current role is impossible

`gold/rules/timeline_consistency.py`

Two roles both marked ongoing is a contradiction in the document itself, not
a judgement about the candidate. Proven by logic, not by measurement.

### G5. Owning a team at E1/E2 contradicts the title — at any size

`gold/rules/responsibility_mismatch.py`

At E1/E2 the ladder says work is checked before it ships and design decisions
are not yet owned. Owning a team is an E5 responsibility. So the rule needs
no size threshold: **any** team contradicts the title, and "any" follows the
ladder's definition rather than a tuned cut-off.

Counts as ownership: owning a team, holding direct reports, managing a counted
group of people.

### G6. Mentoring is not management

`gold/rules/responsibility_mismatch.py`

"Mentored three juniors" is normal from E3 and is never treated as a scope
claim. Without this rule, ordinary senior behaviour would read as a
contradiction.

### G7. A budget of £1m+ at E1/E2 contradicts the title

`gold/rules/responsibility_mismatch.py` → `BUDGET_MILLIONS_FLAG = 1.0`

A budget is an E5+ responsibility. One million is a conservative floor: large
enough that no description mentions it incidentally. The figure rests on the
ladder's definition of scope.

### G8. A team of 30+ is above what an E3/E4 role leads

`gold/rules/responsibility_mismatch.py` → `TEAM_FAR_ABOVE_LEVEL = 30`,
`BANDS_BELOW_TEAM_OWNERSHIP = {E3, E4}`

The one gold threshold not taken from the ladder itself, so it is a
conservative floor rather than a calibrated boundary.

### G9. A role stating no seniority level is not judged

`gold/rules/responsibility_mismatch.py`

Levels are never inferred. A CV lists only a few recent jobs, so an honest
Senior's first listed role shows no prior months and would be read as junior.
Rows with no stated level are left out, and a candidate with no levelled role
is `not_evaluated` rather than `confirmed`.

### G10. An employer is confirmed when the register holds the same name

`gold/rules/company_verification.py` → `classify_status()`. The name
comparison lives in `external/companies_house/name_matching.py`.

Names are compared by their words, after normalizing: lowercase, punctuation
stripped, and legal suffixes removed (`limited`, `ltd`, `llc`, `inc`, `plc`,
`corp`, `gmbh`, `llp`, …) — so "Monzo Bank Ltd" and "MONZO BANK LIMITED" are
the same name.

| Comparison | Status |
|---|---|
| the same words, in any order | `confirmed` |
| one name's words all present in the other ("Monzo" / "Monzo Bank Limited") | `partial_match` |
| neither, or no candidate at all | `unconfirmed` |

**No score and no threshold.** The three outcomes follow from word
comparison, so each verdict can be checked by eye. A typo is `unconfirmed`,
not a near miss: there is no fuzzy matching.

`partial_match` is its own answer, not a weaker `confirmed`. "Monzo" for
"Monzo Bank Limited" is almost certainly the same company; "Smith Consulting"
for "Smith Consulting Group Holdings" may not be. The signal says it cannot
tell.

**Limitation: Companies House registers UK companies only, so this signal
fully verifies UK CVs.** For an employer in another country `unconfirmed`
means this register cannot confirm it, not that the company is invented.

A search returning nothing is cached as a NOT_FOUND sentinel, so an
unfindable employer is not re-queried on every run.

---

## Reference — what do we compare against?

### R1. The seniority ladder is cited, not invented

`reference/seniority_ladder.py`

Source: Eden Capital Careers, "Engineering Titles Explained". E1–E7 mapped to
minimum years of prior experience: E1 0y, E2 1y, E3 2y, E4 4y, E5 7y, E6 11y,
E7 15y.

Every threshold in a trust signal must answer "where does that number come
from?" — taking the ladder from a published guide makes each minimum citable
instead of chosen because it scored well on our own data.

Two deliberate reading decisions, both conservative:

1. **The lower bound of each band** is used — the fewest years at which the
   guide describes anyone holding the title. A claim is only ever measured
   against the most generous reading.
2. **Manager and Director are not on the guide's IC ladder.** They are mapped
   by matching scope — Manager → E5, Director → E6 — and flagged in the data
   as our inference, not the source's.

### R2. A reviewed CSV is the source of truth; the dim_ table is a copy

`reference/loaders/load_dim_*.py`

Full refresh on every load. A correction is a CSV edit plus a rerun, so every
change to a vocabulary is a git diff with an author and a date.

### R3. A reviewed CSV must not contradict itself

`reference/parsing/`

A missing column, a blank key, a repeated key, or a file with no rows is an
error, not a warning. A duplicated key would otherwise resolve to whichever
row was read last. A location token with no country is rejected as a
half-finished review. An alias claimed by two different canonical skills is
rejected outright.

---

