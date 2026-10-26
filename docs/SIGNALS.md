# Reading the signals

Each signal reports **findings** — what was noticed, with its size — and a
**confidence** derived from them. There is no score.

The confidence says whether the claim the signal examined can be believed: the
employment timeline, or the responsibilities stated in a role. It is not a
judgement of the person, and it does not describe the finding. 

| Value | Means |
|---|---|
| `confirmed` | nothing was found against it |
| `possible` | only weak evidence against it — worth a look |
| `not_confirmed` | proven evidence against it — a person should review |
| `not_evaluated` | there was nothing to judge (no datable role, or no stated level) |

Evidence strength decides the confidence: any `proven` finding gives
`not_confirmed`; `suggestive` only gives `possible`; nothing gives `confirmed`.
A `data_issue` never counts against the candidate — it records that our own
extraction failed.

## Timeline consistency

Reads dates only. `months` is the measured size of the finding.

| Finding | Fires when | Evidence | Read as |
|---|---|---|---|
| `employment_overlap_minor` | two roles overlap 2–3 months | suggestive | could be a handover |
| `employment_overlap` | overlap of 4–12 months | proven | two full-time jobs at once |
| `employment_overlap_severe` | overlap over 12 months | proven | the same, for over a year |
| `long_gap` | 7–12 months with no role | proven | unexplained time |
| `very_long_gap` | over 12 months with no role | proven | the same, over a year |
| `seniority_implausible` | a level claimed over 72 months earlier than the ladder expects | suggestive | the CV may simply not list the earlier career |
| `multiple_current_roles` | more than one role marked current | proven | logically impossible |
| `unevaluable_dates` | a role's dates could not be parsed | data issue | our limit, not the candidate's claim |

An overlap of one month or less is ignored: at month precision a handover and a
real overlap look the same.

The 72-month margin is larger than the ladder's own minimum for Mid (2 years)
and Senior (4 years), so this check can only fire on Staff, Lead, Manager,
Principal and Director claims.

## Responsibility mismatch

Reads what the candidate says they were responsible for, and compares it with
the scope the published ladder gives the title they claim. `claimed` is the
number read out of the description — people, or millions of currency.

The ladder is Eden Capital Careers, "Engineering Titles Explained"
(https://edencapitalcareers.com/guides/engineering-titles-explained), mapping
E1–E7 to years of experience and scope. It is cited, not invented — see
`reference/seniority_ladder.py`.

| Finding | Fires when | Evidence | Read as |
|---|---|---|---|
| `team_ownership_at_junior_level` | an E1/E2 role claims managing one or more people | proven | the ladder defines these levels as not owning a team |
| `budget_ownership_at_junior_level` | an E1/E2 role claims a budget of £1m or more | suggestive | possible, but unusual |
| `team_far_above_level` | an E3/E4 role claims 30 or more people | suggestive | a conservative floor, not a calibrated boundary |

A role stating no seniority level is skipped — there is nothing to contradict,
and the level is never inferred. A candidate with no levelled role at all is
`not_evaluated`.

## Company verification

One row per employer, not per candidate, and no confidence column — the status
is the verdict.

| Status | Fires when | Read as |
|---|---|---|
| `confirmed` | the register holds the same words, in any order, ignoring case and `Ltd`/`Limited` | a company of that name exists |
| `partial_match` | one name's words are all contained in the other ("Monzo" / "Monzo Bank Limited") | similar, not the same — nothing consumes this (F4) |
| `unconfirmed` | nothing in the register matches | the employer could not be found |

Two limits to state wherever this signal is reported:

- `confirmed` means a company of that name is registered, not that the
  candidate worked there.
- A misspelling inside a word is `different`, so `"Ancme Ltd"` against
  `"Acme Ltd"` is `unconfirmed`. There is no fuzzy matching, deliberately (F3).
