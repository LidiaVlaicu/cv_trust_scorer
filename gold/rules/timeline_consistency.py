"""
The rules behind gold.signal_timeline_consistency

A trust signal, one row per candidate, answering: is this employment timeline
internally possible?

It reports FINDINGS, not a score. There is deliberately no weighted total,
because any set of weights ("an overlap costs 25 points") would be an opinion
that cannot be defended. Every number in the output is either a measurement
taken from the data or a threshold validated against labelled CVs.

Four checks, all pure date arithmetic:

    1. overlapping employment   two roles covering the same months
    2. unexplained gaps         months with no role at all
    3. seniority reached too fast   a level claimed far earlier than the
                                    published ladder allows for
                                    (reference/seniority_ladder.py)
    4. multiple current roles   more than one role marked as ongoing

Each finding carries an `evidence` strength measured on the 300 labelled CVs
in bronze.raw_cv_texts (see evaluation/timeline_consistency.py):

    proven      occurred only in known-inconsistent CVs (100% precision)
    suggestive  also occurred in legitimate CVs
    data_issue  our extraction failed, not a claim by the candidate

Those roll up into one `confidence` value per candidate - how much the
timeline can be trusted: confirmed, possible, not_confirmed, not_evaluated.

Two checks were tested and dropped for not discriminating at all: seniority
regression (10% of inconsistent CVs vs 5% of legitimate) and short tenure
(5.3% vs 5.3%). Normal careers contain both.

What this signal deliberately does NOT check: whether the role *descriptions*
match the titles (a Graduate claiming to direct 25 engineers). That
contradiction lives in the text, not in the dates, and has its own signal.

This module is the pure core: date arithmetic and thresholds only, no
warehouse and no Dagster. The I/O shell lives in
gold/assets/timeline_consistency.py.
"""

from datetime import date, datetime

from reference import seniority_ladder as ladder

# ── Thresholds, each justified by the labelled evaluation ─────────────────

# When one role ends and the next starts in the same month they share a single
# transition month; month precision cannot tell a real overlap from a handover.
# Two or more months means two jobs genuinely ran at once.
OVERLAP_TOLERANCE_MONTHS = 1

# Real careers contain gaps (study, parental leave, job hunting), so these are
# defensible real-world values rather than the ones that would best separate
# this particular dataset.
GAP_FLAG_MONTHS = 6
LONG_GAP_FLAG_MONTHS = 12

# Months of prior experience the published ladder expects before each level
# (reference/seniority_ladder.py). These MEASURE a shortfall; they
# are not the flag threshold - see SENIORITY_SHORTFALL_FLAG_MONTHS. Levels
# absent from the ladder are never flagged.
MIN_EXPERIENCE_MONTHS = ladder.MIN_EXPERIENCE_MONTHS

# Only a shortfall too large for a short CV to explain is flagged.
#
# A CV lists only its most recent roles, so prior experience read off one
# undercounts the real career - and undercounts it worst at the top of the
# ladder, where more of the career is missing from the page. A legitimate
# Principal whose CV shows three jobs presents ~5 years against the ladder's
# 11, through no fault of their own.
#
# Six years is the margin at which that bias is exhausted. Measured on the 300
# labelled CVs, flagging a shortfall above:
#
#     4 years  ->  83% precision, 19% recall   (6 false positives, all Principal)
#     5 years  ->  82% precision, 15% recall
#     6 years  ->  92% precision, 15% recall   (2 false positives, both Principal)
#
# Six years keeps the recall of a lower threshold while leaving only the two
# false positives that CV truncation fully explains. The remaining error is a
# known, stated limitation of reading careers off CVs rather than a tuned
# constant: no threshold can recover history the document does not contain.
#
# A consequence worth stating: a six-year margin is larger than the ladder's
# own minimum for Mid (2y) and Senior (4y), so in practice this check can only
# ever fire on E5+ claims - Staff, Lead, Manager, Principal, Director. A
# prematurely claimed "Senior" is beyond what CV dates can evidence, and is
# left to the responsibility signal, which reads the description instead.
SENIORITY_SHORTFALL_FLAG_MONTHS = 72

# How strong a single finding is as evidence against the timeline.
PROVEN = "proven"          # occurred only in known-inconsistent CVs
SUGGESTIVE = "suggestive"  # also occurred in legitimate CVs
DATA_ISSUE = "data_issue"  # our extraction failed, not the candidate's claim

# Our confidence in the candidate's timeline, derived from the evidence found.
CONFIRMED = "confirmed"          # nothing found against it
POSSIBLE = "possible"            # suggestive evidence only, worth a look
NOT_CONFIRMED = "not_confirmed"  # proven evidence of an impossible timeline
NOT_EVALUATED = "not_evaluated"  # no role could be placed on a timeline

# Measured precision of each finding on the 300 labelled CVs. Regenerate with
# evaluation/timeline_consistency.py after changing any threshold.
EVIDENCE = {
    "employment_overlap_minor": SUGGESTIVE,  # 90% precision (9 of 10)
    "employment_overlap": PROVEN,            # 100% (8 of 8)
    "employment_overlap_severe": PROVEN,     # 100% (3 of 3)
    "long_gap": PROVEN,                      # 100% (2 of 2)
    "very_long_gap": PROVEN,                 # 100% (2 of 2)
    # 92% (22 of 24). The two legitimate CVs it fires on are both Principals
    # whose earlier career is not listed - see SENIORITY_SHORTFALL_FLAG_MONTHS.
    "seniority_implausible": SUGGESTIVE,
    "multiple_current_roles": PROVEN,        # logically impossible
    "unevaluable_dates": DATA_ISSUE,
}

# ── Pure core ─────────────────────────────────────────────────────────────
def months_between(start: date, end: date) -> int:
    """Whole months from `start` to `end`; negative if `end` precedes `start`."""
    return (end.year - start.year) * 12 + (end.month - start.month)


def _first_of_next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _as_date(value) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _role_spans(jobs: list[dict], as_of: date) -> list[tuple[date, date, dict]]:
    """
    (start, end_exclusive, job) per evaluable role, sorted by start.

    A CV date is a whole month: "ended December 2017" means the candidate
    worked through December, so the interval ends at 1 January 2018. Using a
    half-open interval this way makes the arithmetic match reality — a role
    ending in December followed by one starting in January is continuous, and
    the duration counts December itself.

    A role with no end date runs to `as_of` — which is why `as_of_date` is
    recorded on the output: the same CV answers differently next year.
    """
    spans = []
    for job in jobs:
        start = _as_date(job.get("start_date"))
        if start is None:
            continue  # cannot place this role on a timeline
        end = _as_date(job.get("end_date")) or as_of
        if end < start:
            end = start  # silver already rejects this; stay defensive
        spans.append((start, _first_of_next_month(end), job))
    return sorted(spans, key=lambda span: (span[0], span[1]))


def _union_months(spans: list[tuple[date, date, dict]]) -> int:
    """Months actually worked, counting overlapping months only once."""
    total, covered_until = 0, None
    for start, end, _ in spans:
        if covered_until is None or start > covered_until:
            total += months_between(start, end)
            covered_until = end
        elif end > covered_until:
            total += months_between(covered_until, end)
            covered_until = end
    return total


def max_overlap_months(spans) -> int:
    """Worst overlap in months between any two roles; 0 if within tolerance."""
    worst = 0
    for index, (start_a, end_a, _) in enumerate(spans):
        for start_b, end_b, _ in spans[index + 1:]:
            overlap = months_between(max(start_a, start_b), min(end_a, end_b))
            if overlap > OVERLAP_TOLERANCE_MONTHS:
                worst = max(worst, overlap)
    return worst


def max_gap_months(spans) -> int:
    """Longest stretch with no role at all, in months."""
    worst, covered_until = 0, None
    for start, end, _ in spans:
        if covered_until is not None and start > covered_until:
            worst = max(worst, months_between(covered_until, start))
        covered_until = end if covered_until is None else max(covered_until, end)
    return worst


def seniority_shortfall_months(spans) -> int:
    """
    How far short of the ladder's minimum the most premature claim is.

    For each role whose level appears on the published ladder, the experience
    accumulated *before that role started* is compared against the minimum for
    that level. Because a CV lists only recent roles, the result is a lower
    bound on the candidate's real experience, never an exact figure - which is
    why only a large shortfall is acted on.
    """
    worst = 0
    for index, (start, _, job) in enumerate(spans):
        level = job.get("seniority_level")
        # A career legitimately BEGINS at an entry-level title: holding no prior
        # experience before a first "Junior" role is normal, not a shortfall.
        # The ladder's 0-2 year bands are therefore not requirements here.
        if ladder.is_junior_level(level):
            continue
        required = MIN_EXPERIENCE_MONTHS.get(level)
        if required is None:
            continue
        earlier = [
            (span_start, min(span_end, start), span_job)
            for span_start, span_end, span_job in spans[:index]
            if span_start < start
        ]
        worst = max(worst, required - _union_months(earlier))
    return worst


def find_timeline_issues(jobs: list[dict], as_of: date) -> list[dict]:
    """
    Every finding for one candidate, as {name, months, evidence}.

    An empty list means no timeline inconsistency was detected. Measurements
    are reported only when they cross a validated threshold, so the table
    never carries numbers that were not acted on.
    """
    spans = _role_spans(jobs, as_of)
    if not spans:
        return []

    findings: list[tuple[str, int | None]] = []

    overlap = max_overlap_months(spans)
    if overlap > 12:
        findings.append(("employment_overlap_severe", overlap))
    elif overlap > 3:
        findings.append(("employment_overlap", overlap))
    elif overlap > OVERLAP_TOLERANCE_MONTHS:
        findings.append(("employment_overlap_minor", overlap))

    gap = max_gap_months(spans)
    if gap > LONG_GAP_FLAG_MONTHS:
        findings.append(("very_long_gap", gap))
    elif gap > GAP_FLAG_MONTHS:
        findings.append(("long_gap", gap))

    shortfall = seniority_shortfall_months(spans)
    if shortfall > SENIORITY_SHORTFALL_FLAG_MONTHS:
        findings.append(("seniority_implausible", shortfall))

    if sum(1 for job in jobs if job.get("is_current")) > 1:
        findings.append(("multiple_current_roles", None))

    if len(spans) < len(jobs):
        findings.append(("unevaluable_dates", len(jobs) - len(spans)))

    return [
        {"name": name, "months": months, "evidence": EVIDENCE[name]}
        for name, months in findings
    ]


def timeline_confidence(findings: list[dict], jobs_evaluated: int) -> str:
    """
    How much the timeline can be trusted, by a single stated rule rather than
    a score threshold:

        no role could be placed on a timeline -> not_evaluated
        any proven evidence                   -> not_confirmed
        suggestive evidence only              -> possible
        none                                  -> confirmed

    data_issue findings never decide the verdict: a gap in our extraction is
    not evidence against the candidate.
    """
    if jobs_evaluated == 0:
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
    as_of: date,
    evaluated_at: datetime,
) -> list[dict]:
    """One signal row per candidate. Pure: same inputs, same output."""
    by_candidate: dict[str, list[dict]] = {}
    for row in work_experience:
        by_candidate.setdefault(row["submission_id"], []).append(row)

    timestamp = evaluated_at.isoformat()
    signal_rows = []
    for submission_id, jobs in sorted(by_candidate.items()):
        findings = find_timeline_issues(jobs, as_of)
        signal_rows.append({
            "submission_id": submission_id,
            "confidence": timeline_confidence(findings, len(_role_spans(jobs, as_of))),
            "findings": findings,
            "as_of_date": as_of.isoformat(),
            "evaluated_at": timestamp,
        })
    return signal_rows

