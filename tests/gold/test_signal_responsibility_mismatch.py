"""
Tests for gold.signal_responsibility_mismatch.

The extraction tests are deliberately heavy on NEGATIVE cases. An earlier
version of these patterns matched any number standing near a management verb,
and every string in test_numbers_that_are_not_people was a false positive it
produced against the real data.
"""

from datetime import datetime, timezone

import pytest

from gold.assets.signal_responsibility_mismatch import run_signal_responsibility_mismatch
from gold.rules.responsibility_mismatch import (
    BUDGET_MILLIONS_FLAG,
    TEAM_FAR_ABOVE_LEVEL,
    budget_millions,
    build_signal_rows,
    find_responsibility_mismatches,
    people_managed,
    responsibility_confidence,
)

EVALUATED_AT = datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc)


def job(seniority, description, experience_id="cv_1_job1", submission_id="cv_1"):
    return {
        "submission_id": submission_id,
        "experience_id": experience_id,
        "job_title": "Engineer",
        "seniority_level": seniority,
        "description": description,
    }


def names(jobs):
    return [finding["name"] for finding in find_responsibility_mismatches(jobs)]


# ── extracting a headcount ────────────────────────────────────────────────
@pytest.mark.parametrize(
    "description, expected",
    [
        ("Managed a cross-functional team of 28 engineers", 28),
        ("Directed department of 50+ professionals", 50),
        ("Mentored team of 22 across three continents", 22),
        ("Responsible for 18 direct reports", 18),
        ("Led 45 engineers through a replatforming", 45),
        ("headed team of 18", 18),
        ("Managed and directed a team of 22 engineers", 22),
    ],
)
def test_headcounts_that_are_real_authority(description, expected):
    assert people_managed(description) == expected


@pytest.mark.parametrize(
    "description",
    [
        # every one of these was a false positive from the first pattern set
        "Led architectural design of an API serving 500,000 requests per day",
        "Managed AWS infrastructure supporting 15+ services across EC2",
        "Directing implementation of a platform affecting 500+ employees",
        "Developed dashboards used by 200+ staff members",
        "Built dbt models used by 30+ analysts",
        "Improved data accessibility for 45 analysts and researchers",
        "Migrated 12 applications to AWS with zero unplanned downtime",
        "Refactored a component used by 15 developers across three teams",
        "Reduced defect detection time from 8 hours to 15 minutes",
    ],
)
def test_numbers_that_are_not_people(description):
    """Users of the work, things migrated, and durations are not authority."""
    assert people_managed(description) == 0


def test_mentoring_alone_is_not_management():
    """
    The ladder has E3 owning features and guiding juniors, so a count of
    mentees is not a claim of scope. Only a team, reports, or a managed group
    of people counts.
    """
    assert people_managed("Mentored 4 junior engineers on code review") == 0
    assert people_managed("Coached 3 interns during the summer programme") == 0
    # but naming a team as the unit is a scope claim whatever the verb
    assert people_managed("Mentored a team of 24 engineers") == 24


def test_the_largest_claim_in_a_description_wins():
    assert people_managed(
        "Led a team of 6 engineers, later managing 30 engineers after a merger"
    ) == 30


def test_no_description_claims_nothing():
    assert people_managed(None) == 0
    assert people_managed("") == 0
    assert budget_millions(None) == 0.0


# ── extracting a budget ───────────────────────────────────────────────────
@pytest.mark.parametrize(
    "description, expected",
    [
        ("Managed an $8.7 million annual research budget", 8.7),
        ("Owned a budget of 4.2 million for tooling", 4.2),
        ("Accountable for P&L of GBP 12 million", 12.0),
    ],
)
def test_budgets_that_are_owned(description, expected):
    assert budget_millions(description) == expected


@pytest.mark.parametrize(
    "description",
    [
        "Increased gross profit by GBP 4.7m annually",
        "Worked on payment systems handling over £50 million in transactions",
        "Built a platform serving 10 million concurrent users",
        "Generated $2 million in additional revenue",
    ],
)
def test_money_that_is_not_a_budget(description):
    """Money generated, processed, or counted in users is not money owned."""
    assert budget_millions(description) == 0.0


# ── check 1: team ownership at an E1/E2 level ─────────────────────────────
def test_a_junior_who_directed_a_team_is_flagged():
    finding, = find_responsibility_mismatches(
        [job("Junior", "Directed a team of 22 engineers across two sites")]
    )
    assert finding == {
        "name": "team_ownership_at_junior_level",
        "experience_id": "cv_1_job1",
        "level": "Junior",
        "claimed": 22.0,
        "evidence": "proven",
    }


@pytest.mark.parametrize("level", ["Intern", "Apprentice", "Graduate", "Junior"])
def test_every_e1_e2_level_is_checked(level):
    assert names([job(level, "Managed a team of 12 engineers")]) == [
        "team_ownership_at_junior_level"
    ]


def test_any_team_size_counts_at_a_junior_level():
    """
    No size threshold: of 232 labelled E1/E2 descriptions, not one legitimate
    CV claims the candidate managed anybody. The ladder puts team ownership at
    E5, so the contradiction does not depend on how big the team was.
    """
    assert names([job("Junior", "Led a team of 3 engineers")]) == [
        "team_ownership_at_junior_level"
    ]


def test_a_junior_doing_junior_things_is_not_flagged():
    assert names([
        job("Junior", "Built REST endpoints in Python and wrote unit tests, "
                      "mentored 2 interns, dashboards used by 40 analysts")
    ]) == []


# ── check 2: budget ownership at an E1/E2 level ───────────────────────────
def test_a_junior_owning_a_large_budget_is_flagged():
    finding, = find_responsibility_mismatches(
        [job("Graduate", "Owned a budget of 4.2 million for vendor selection")]
    )
    assert finding["name"] == "budget_ownership_at_junior_level"
    assert (finding["claimed"], finding["evidence"]) == (4.2, "suggestive")


def test_a_budget_below_the_floor_is_not_flagged():
    assert names([job("Junior", "Managed a budget of 0.4 million")]) == []


def test_both_junior_checks_can_fire_on_one_role():
    assert sorted(names([
        job("Graduate", "Directed a team of 25 engineers and managed "
                        "an $8.7 million research budget")
    ])) == [
        "budget_ownership_at_junior_level",
        "team_ownership_at_junior_level",
    ]


# ── check 3: a team far above the stated level ────────────────────────────
def test_a_senior_claiming_a_very_large_team_is_flagged():
    finding, = find_responsibility_mismatches(
        [job("Senior", "Led 150 engineers across the platform organisation")]
    )
    assert finding["name"] == "team_far_above_level"
    assert (finding["level"], finding["claimed"]) == ("Senior", 150.0)


def test_a_senior_leading_a_normal_team_is_not_flagged():
    assert names([job("Senior", "Led a team of 6 engineers")]) == []


def test_the_far_above_boundary():
    below = [job("Senior", f"Led a team of {TEAM_FAR_ABOVE_LEVEL - 1} engineers")]
    at_or_above = [job("Senior", f"Led a team of {TEAM_FAR_ABOVE_LEVEL} engineers")]
    assert names(below) == []
    assert names(at_or_above) == ["team_far_above_level"]


def test_a_principal_leading_a_large_team_is_normal():
    """E6 is cross-org technical authority, so a big team is in scope."""
    assert names([job("Principal", "Led 52 engineers across four teams")]) == []


def test_staff_is_not_checked_for_a_large_team():
    """E5 is defined as technical lead for a team, so the claim fits."""
    assert names([job("Staff", "Managed a team of 28 engineers")]) == []


# ── roles with no stated level ────────────────────────────────────────────
def test_a_role_with_no_stated_level_is_skipped():
    """
    Inferring the level from prior experience was tested and rejected: 74%
    accurate, and it dropped these rules from 100% to 14% precision.
    """
    assert names([job(None, "Directed a team of 40 engineers")]) == []


def test_a_candidate_with_no_levelled_role_is_not_evaluated():
    rows = build_signal_rows(
        [job(None, "Directed a team of 40 engineers")], evaluated_at=EVALUATED_AT
    )
    assert rows[0]["confidence"] == "not_evaluated"
    assert rows[0]["findings"] == []


# ── confidence rollup ─────────────────────────────────────────────────────
def test_confidence_follows_the_strongest_evidence():
    proven = [{"evidence": "proven"}, {"evidence": "suggestive"}]
    assert responsibility_confidence(proven, levelled_roles=3) == "not_confirmed"
    assert responsibility_confidence([{"evidence": "suggestive"}], 3) == "possible"
    assert responsibility_confidence([], 3) == "confirmed"
    assert responsibility_confidence([], 0) == "not_evaluated"


# ── rows ──────────────────────────────────────────────────────────────────
def test_one_row_per_candidate_with_findings_from_every_role():
    work_experience = [
        job("Junior", "Directed a team of 22 engineers", "cv_1_job1", "cv_1"),
        job("Senior", "Built a payments service", "cv_1_job2", "cv_1"),
        job("Senior", "Led a team of 5 engineers", "cv_2_job1", "cv_2"),
    ]
    rows = build_signal_rows(work_experience, evaluated_at=EVALUATED_AT)
    assert [row["submission_id"] for row in rows] == ["cv_1", "cv_2"]
    assert rows[0]["confidence"] == "not_confirmed"
    assert [f["experience_id"] for f in rows[0]["findings"]] == ["cv_1_job1"]
    assert rows[1] == {
        "submission_id": "cv_2",
        "confidence": "confirmed",
        "findings": [],
        "evaluated_at": EVALUATED_AT.isoformat(),
    }


def test_build_signal_rows_is_pure():
    work_experience = [job("Junior", "Managed a team of 20 engineers")]
    first = build_signal_rows(work_experience, evaluated_at=EVALUATED_AT)
    second = build_signal_rows(work_experience, evaluated_at=EVALUATED_AT)
    assert first == second


# ── the run function, against a fake warehouse ────────────────────────────
class FakeWarehouse:
    def __init__(self, work_experience):
        self._work_experience = work_experience
        self.written = None

    def read_work_experience(self):
        return self._work_experience

    def replace_signal(self, rows):
        self.written = rows


def test_run_writes_every_candidate_and_reports_a_summary():
    warehouse = FakeWarehouse([
        job("Junior", "Directed a team of 22 engineers", "cv_1_job1", "cv_1"),
        job("Senior", "Built a payments service", "cv_2_job1", "cv_2"),
    ])
    messages = []

    result = run_signal_responsibility_mismatch(
        warehouse,
        now=lambda: EVALUATED_AT,
        report=messages.append,
    )

    assert len(warehouse.written) == 2
    assert result["candidates"] == 2
    assert result["confidence"] == {"not_confirmed": 1, "confirmed": 1}
    assert result["findings"] == {"team_ownership_at_junior_level": 1}
    assert any("Wrote 2 candidate rows" in message for message in messages)


def test_the_budget_floor_is_the_documented_value():
    """Pinned so a change to the threshold has to be deliberate."""
    assert BUDGET_MILLIONS_FLAG == 1.0
    assert TEAM_FAR_ABOVE_LEVEL == 30
