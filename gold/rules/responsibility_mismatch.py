"""
The rules behind gold.signal_responsibility_mismatch

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
an `evidence` strength, and those roll up into one `confidence` per candidate.

Why check 1 has no size threshold
---------------------------------
At E1/E2 the ladder says design decisions are not yet owned, so owning a team
of any size contradicts the title. "Any" follows the ladder's definition rather
than a tuned cut-off.

Mentoring is deliberately not management
----------------------------------------
"Mentored three juniors" is normal from E3 and is not treated as a scope claim.
Only owning a team, holding direct reports, or managing a counted group of
people counts.

What this signal deliberately does NOT do
-----------------------------------------
It does not infer a seniority level for the role rows that state none. A CV
lists only a few recent jobs, so an honest Senior's first listed role shows no
prior months and would be read as junior. Rows with no stated level are left
out.

This module is the pure core: the extraction patterns and the rules, with
no warehouse and no Dagster. The I/O shell lives in
gold/assets/responsibility_mismatch.py.
"""

import re
from datetime import datetime

from reference import seniority_ladder as ladder

# ── Thresholds ────────────────────────────────────────────────────────────

# Check 1 has no size threshold at all; see the module docstring.

# A budget is an E5+ responsibility. One million is a conservative floor: large
# enough that no description mentions it incidentally. The figure rests on the
# ladder's definition of scope.
BUDGET_MILLIONS_FLAG = 1.0

# Check 3: a team of thirty is beyond what an E3/E4 role leads under the
# ladder. This is the one threshold here not taken from the ladder itself, so
# treat it as a conservative floor rather than a calibrated boundary.
TEAM_FAR_ABOVE_LEVEL = 30
BANDS_BELOW_TEAM_OWNERSHIP = frozenset({"E3", "E4"})

PROVEN = "proven"
SUGGESTIVE = "suggestive"

CONFIRMED = "confirmed"
POSSIBLE = "possible"
NOT_CONFIRMED = "not_confirmed"
NOT_EVALUATED = "not_evaluated"

# How strong each finding is as evidence against the stated level.
EVIDENCE = {
    "team_ownership_at_junior_level": PROVEN,
    "budget_ownership_at_junior_level": SUGGESTIVE,
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

