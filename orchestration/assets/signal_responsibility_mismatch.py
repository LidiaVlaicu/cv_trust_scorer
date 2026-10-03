"""
silver.silver_work_experience -> gold.signal_responsibility_mismatch

A trust signal, one row per candidate, answering: do the responsibilities
claimed in a role description contradict the seniority of its job title?

The timeline signal reads dates. This one reads what the candidate says they
were responsible for, and compares it against the scope the published ladder
assigns to the title they gave themselves
(reference/seniority_ladder.py):

    E1  Intern / Graduate     work is checked before it ships
    E2  Junior                assigned tasks, with review; no design ownership
    E3  Mid                   owns well-scoped features
    E4  Senior                owns a component or subsystem
    E5  Staff / Lead          technical lead for a TEAM
    E6  Principal             cross-team and cross-org authority

Owning a team is an E5 responsibility by that definition. So a Junior who
claims to have directed a team of 28 is not merely impressive - the claim and
the title describe two different levels, three bands apart.

Three checks, all on text the candidate wrote:

    1. team ownership at an E1/E2 level   any team, however small
    2. budget ownership at an E1/E2 level a budget is an E5+ responsibility
    3. a team far above the stated level   E3/E4 claiming more than any
                                           legitimate E5 was observed to claim

As in the timeline signal there is deliberately no score. Each finding carries
an `evidence` strength measured on the 300 labelled CVs in bronze.raw_cv_texts,
and those roll up into one `confidence` per candidate.

Why check 1 has no size threshold
---------------------------------
Of 232 E1/E2 role descriptions in the labelled set, NOT ONE legitimate CV
claims the candidate managed anybody. All 12 such claims come from CVs labelled
inconsistent. The rule therefore needs no tuned cut-off: at these levels the
ladder says design decisions are not yet owned, and the data contains no honest
counter-example. The smallest claim observed is 18 people, so the data cannot
by itself distinguish "any team" from "a team of 18 or more"; "any" is chosen
because it follows the ladder's definition rather than this dataset's minimum.

Mentoring is deliberately not management
----------------------------------------
"Mentored three juniors" is normal from E3 and is not treated as a scope claim.
Only owning a team, holding direct reports, or managing a counted group of
people counts. No E1/E2 row in the labelled set claims mentoring without also
claiming a team, so this costs no detections; it is a guard against a false
positive this dataset happens not to contain.

What this signal deliberately does NOT do
-----------------------------------------
It does not infer a seniority level for the 308 role rows that state none. That
was tested: inferring "junior" from prior experience on the CV is only 74%
accurate, because a CV lists a few recent jobs and an honest Senior's first
listed role shows no prior months. Applying these rules to inferred levels
collapsed precision from 100% to 14%. Rows with no stated level are left out.

Structure: a pure core and a thin I/O shell, as in the other signals.
"""

import os
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Callable, Protocol

from dagster import asset, get_dagster_logger
from google.cloud import bigquery

from reference import seniority_ladder as ladder

SIGNAL_TABLE = "signal_responsibility_mismatch"
SIGNAL_SCHEMA = [
    bigquery.SchemaField("submission_id", "STRING", mode="REQUIRED"),
    # our confidence in the candidate's stated responsibilities
    bigquery.SchemaField("confidence", "STRING", mode="REQUIRED"),
    bigquery.SchemaField(
        "findings",
        "RECORD",
        mode="REPEATED",
        fields=[
            bigquery.SchemaField("name", "STRING", mode="REQUIRED"),
            # the role whose description carries the claim, so a reviewer can
            # find the sentence; the finding is not checkable without it
            bigquery.SchemaField("experience_id", "STRING", mode="REQUIRED"),
            # the seniority level contradicted - half of the contradiction
            bigquery.SchemaField("level", "STRING", mode="REQUIRED"),
            # size of the claim. People for the team findings, millions of
            # currency for the budget finding; which it is follows from the
            # name, as `months` does in the timeline signal.
            bigquery.SchemaField("claimed", "FLOAT64", mode="REQUIRED"),
            bigquery.SchemaField("evidence", "STRING", mode="REQUIRED"),
        ],
    ),
    bigquery.SchemaField("evaluated_at", "TIMESTAMP", mode="REQUIRED"),
]

# ── Thresholds ────────────────────────────────────────────────────────────

# Check 1 has no size threshold at all; see the module docstring.

# A budget is an E5+ responsibility. One million is a conservative floor: it is
# large enough that no description mentions it incidentally. Only two E1/E2
# rows in the labelled set claim a budget (both from inconsistent CVs), so this
# figure rests on the ladder's definition of scope, not on measurement.
BUDGET_MILLIONS_FLAG = 1.0

# Check 3: across all 150 legitimate CVs the largest team an E3/E4 role claims
# is 25 people, and at E5/E6 - the bands that are supposed to lead teams - it
# is only 8. Thirty therefore sits above the whole observed legitimate range,
# not merely above the band's own ceiling.
#
# Honest limits of this number: it is the one threshold here read off our own
# dataset rather than from the ladder, and only two roles exceed it. It is a
# conservative floor, not a calibrated boundary.
TEAM_FAR_ABOVE_LEVEL = 30
BANDS_BELOW_TEAM_OWNERSHIP = frozenset({"E3", "E4"})

PROVEN = "proven"
SUGGESTIVE = "suggestive"

CONFIRMED = "confirmed"
POSSIBLE = "possible"
NOT_CONFIRMED = "not_confirmed"
NOT_EVALUATED = "not_evaluated"

# Measured on the 300 labelled CVs. Regenerate with
# scripts/evaluate_responsibility_signal.py after changing any threshold.
EVIDENCE = {
    # 12 of 12, against 0 of 232 legitimate E1/E2 descriptions
    "team_ownership_at_junior_level": PROVEN,
    # 2 of 2 - correct on this data, but too few rows to call proven
    "budget_ownership_at_junior_level": SUGGESTIVE,
    # 2 of 2 - likewise thin
    "team_far_above_level": SUGGESTIVE,
}

# ── Extraction patterns ───────────────────────────────────────────────────
#
# Every pattern requires a people noun or an explicit management construction.
# An earlier version matched any number near a management verb and read
# "serving 500,000 requests" as 500 people, "supporting 15+ services" as 15
# people, and "used by 30+ analysts" - people who USE the work - as reports.
# Requiring the noun removed all of those.

_PEOPLE = (
    r"(?:engineers|developers|software engineers|data scientists|data engineers"
    r"|analysts|professionals|researchers|people|staff|employees|team members"
    r"|interns|scientists)"
)

# "a team of 28", "department of 50+" - names a team as the unit it owns,
# whatever verb introduces it.
_TEAM_OF = re.compile(
    r"(?:team|department|group|division|organisation|organization)\s+of\s+(\d+)",
    re.IGNORECASE,
)
# A reporting line is management by definition.
_DIRECT_REPORTS = re.compile(r"(\d+)\s*\+?\s*direct reports", re.IGNORECASE)
# A management verb governing a count of people.
_MANAGED_PEOPLE = re.compile(
    r"(?:managed|managing|directed|directing|led|leading|oversaw|overseeing"
    r"|supervised|supervising|headed|heading)\s+(\d+)\s*\+?\s*" + _PEOPLE,
    re.IGNORECASE,
)
_TEAM_PATTERNS = (_TEAM_OF, _DIRECT_REPORTS, _MANAGED_PEOPLE)

# A budget must be named as such; "increased gross profit by GBP 4.7m" and
# "handling £50 million in transactions" are money the candidate did not own.
_CURRENCY = r"(?:\$|£|Â£|GBP|EUR|USD)"
_BUDGET_PATTERNS = (
    re.compile(
        rf"(?:budget|p&l|capital expenditure)[^.|]{{0,40}}?{_CURRENCY}?\s?"
        rf"([\d.]+)\s*(?:million|m\b|bn)",
        re.IGNORECASE,
    ),
    re.compile(
        rf"{_CURRENCY}\s?([\d.]+)\s*(?:million|m\b)[^.|]{{0,30}}?(?:budget|p&l)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:managed|managing|oversaw|overseeing|owned|owning)[^.|]{0,25}?"
        r"(?:budget|p&l)[^.|]{0,30}?([\d.]+)\s*(?:million|m\b)",
        re.IGNORECASE,
    ),
)


# ── Pure core ─────────────────────────────────────────────────────────────
def _largest(text: str, patterns) -> float:
    """The largest number any of `patterns` captures in `text`; 0 if none do."""
    largest = 0.0
    for pattern in patterns:
        for match in pattern.finditer(text):
            try:
                largest = max(largest, float(match.group(1)))
            except ValueError:  # a malformed capture such as "4.2.1"
                continue
    return largest


def people_managed(description: str | None) -> int:
    """
    The largest headcount the description claims authority over.

    Counts only owning a team, holding direct reports, or managing a counted
    group of people. People who merely use the candidate's work, and mentees,
    are not authority.
    """
    if not description:
        return 0
    return int(_largest(description, _TEAM_PATTERNS))


def budget_millions(description: str | None) -> float:
    """The largest budget, in millions, the description claims to own."""
    if not description:
        return 0.0
    return _largest(description, _BUDGET_PATTERNS)


def find_responsibility_mismatches(jobs: list[dict]) -> list[dict]:
    """
    Every finding for one candidate, as {name, experience_id, level, claimed,
    evidence}. An empty list means no contradiction was detected.

    Roles with no stated seniority level are skipped: there is nothing to
    contradict, and inferring the level does not work (see module docstring).
    """
    findings: list[tuple[str, dict, str, float]] = []

    for job in jobs:
        level = job.get("seniority_level")
        if not level:
            continue
        band = ladder.ladder_level(level)
        people = people_managed(job.get("description"))
        budget = budget_millions(job.get("description"))

        if ladder.is_junior_level(level):
            if people >= 1:
                findings.append(
                    ("team_ownership_at_junior_level", job, level, float(people))
                )
            if budget >= BUDGET_MILLIONS_FLAG:
                findings.append(
                    ("budget_ownership_at_junior_level", job, level, budget)
                )
        elif band in BANDS_BELOW_TEAM_OWNERSHIP and people >= TEAM_FAR_ABOVE_LEVEL:
            findings.append(("team_far_above_level", job, level, float(people)))

    return [
        {
            "name": name,
            "experience_id": job["experience_id"],
            "level": level,
            "claimed": claimed,
            "evidence": EVIDENCE[name],
        }
        for name, job, level, claimed in findings
    ]


def responsibility_confidence(findings: list[dict], levelled_roles: int) -> str:
    """
    How much the stated responsibilities can be trusted, by one stated rule:

        no role states a seniority level -> not_evaluated
        any proven evidence              -> not_confirmed
        suggestive evidence only         -> possible
        none                             -> confirmed
    """
    if levelled_roles == 0:
        return NOT_EVALUATED
    strengths = {finding["evidence"] for finding in findings}
    if PROVEN in strengths:
        return NOT_CONFIRMED
    if SUGGESTIVE in strengths:
        return POSSIBLE
    return CONFIRMED


def build_signal_rows(
    work_experience: list[dict],
    *,
    evaluated_at: datetime,
) -> list[dict]:
    """One signal row per candidate. Pure: same inputs, same output."""
    by_candidate: dict[str, list[dict]] = {}
    for row in work_experience:
        by_candidate.setdefault(row["submission_id"], []).append(row)

    timestamp = evaluated_at.isoformat()
    signal_rows = []
    for submission_id, jobs in sorted(by_candidate.items()):
        findings = find_responsibility_mismatches(jobs)
        levelled = sum(1 for job in jobs if job.get("seniority_level"))
        signal_rows.append({
            "submission_id": submission_id,
            "confidence": responsibility_confidence(findings, levelled),
            "findings": findings,
            "evaluated_at": timestamp,
        })
    return signal_rows


# ── I/O boundary ──────────────────────────────────────────────────────────
class ResponsibilityWarehouse(Protocol):
    """Everything the responsibility signal needs from the warehouse."""

    def read_work_experience(self) -> list[dict]:
        """`silver_work_experience` rows."""

    def replace_signal(self, rows: list[dict]) -> None:
        """Replaces `signal_responsibility_mismatch` with `rows`."""


class BigQueryResponsibilityWarehouse:
    """ResponsibilityWarehouse backed by BigQuery."""

    def __init__(
        self,
        client: bigquery.Client | None = None,
        silver_dataset: str | None = None,
        gold_dataset: str | None = None,
    ) -> None:
        self._client = client or bigquery.Client(project=os.getenv("GCP_PROJECT_ID"))
        self._silver = silver_dataset or os.getenv("BQ_DATASET_SILVER")
        self._gold = gold_dataset or os.getenv("BQ_DATASET_GOLD")

    def read_work_experience(self) -> list[dict]:
        query = f"""
            SELECT submission_id, experience_id, job_title, seniority_level,
                   description
            FROM `{self._client.project}.{self._silver}.silver_work_experience`
        """
        return [dict(row) for row in self._client.query(query).result()]

    def replace_signal(self, rows: list[dict]) -> None:
        """Full refresh: the signal is a pure function of silver."""
        table_id = f"{self._client.project}.{self._gold}.{SIGNAL_TABLE}"
        job_config = bigquery.LoadJobConfig(
            schema=SIGNAL_SCHEMA,
            write_disposition="WRITE_TRUNCATE",
        )
        self._client.load_table_from_json(rows, table_id, job_config=job_config).result()


# ── Orchestration (dependencies injected) ─────────────────────────────────
def run_signal_responsibility_mismatch(
    warehouse: ResponsibilityWarehouse,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    report: Callable[[str], None] = lambda message: None,
) -> dict:
    """
    Reads silver, compares every role's claims against its stated level, writes
    the gold signal and returns run metadata. The warehouse and clock are
    injected so this runs with no BigQuery and no Dagster.
    """
    evaluated_at = now()

    work_experience = warehouse.read_work_experience()
    report(f"Read {len(work_experience)} work experience rows")

    signal_rows = build_signal_rows(work_experience, evaluated_at=evaluated_at)
    warehouse.replace_signal(signal_rows)
    report(f"Wrote {len(signal_rows)} candidate rows into {SIGNAL_TABLE}")

    confidences = Counter(row["confidence"] for row in signal_rows)
    names = Counter(
        finding["name"] for row in signal_rows for finding in row["findings"]
    )
    report(f"Confidence: {dict(confidences)}")
    report(f"Findings: {dict(names) or 'none'}")

    return {
        "candidates": len(signal_rows),
        "confidence": dict(confidences),
        "findings": dict(names),
    }


# ── ASSET: signal_responsibility_mismatch ─────────────────────────────────
@asset(deps=["silver_work_experience"])
def signal_responsibility_mismatch():
    """
    Trust signal: do the responsibilities claimed contradict the job title?

    Compares what each role description claims authority over - a team, direct
    reports, a budget - against the scope a published engineering ladder
    assigns to the stated seniority level. A Junior who directed a team of 28
    is claiming an E5 responsibility under an E2 title.

    Reports findings rather than a score, each naming the role it came from so
    the claim can be read back, and rolls them up into one confidence value per
    candidate.

    Writes one row per candidate to the gold dataset.
    """
    return run_signal_responsibility_mismatch(
        BigQueryResponsibilityWarehouse(),
        report=get_dagster_logger().info,
    )
