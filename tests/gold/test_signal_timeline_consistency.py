"""
Tests for the timeline-consistency trust signal.

The pure core is exercised on hand-built timelines, then the whole pipeline
runs against an in-memory fake warehouse — no BigQuery, no Dagster.
"""

from datetime import date, datetime, timezone

from gold.assets.signal_timeline_consistency import (
    SIGNAL_SCHEMA,
    run_signal_timeline_consistency,
)
from gold.rules.timeline_consistency import (
    _role_spans,
    _union_months,
    build_signal_rows,
    find_timeline_issues,
    max_gap_months,
    max_overlap_months,
    months_between,
    seniority_shortfall_months,
    timeline_confidence,
)

AS_OF = date(2026, 1, 1)
EVALUATED_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def job(start, end=None, *, seniority=None, current=False, submission="cv_1"):
    return {
        "submission_id": submission,
        "experience_id": f"{submission}_{start}",
        "job_title": "Engineer",
        "seniority_level": seniority,
        "start_date": start,
        "end_date": end,
        "is_current": current,
    }


def spans(jobs):
    return _role_spans(jobs, AS_OF)


def codes(jobs):
    return [finding["name"] for finding in find_timeline_issues(jobs, AS_OF)]


def findings_by_name(jobs):
    return {f["name"]: f for f in find_timeline_issues(jobs, AS_OF)}


# ── month arithmetic and whole-month intervals ────────────────────────────
def test_months_between():
    assert months_between(date(2016, 9, 1), date(2018, 5, 1)) == 20
    assert months_between(date(2020, 1, 1), date(2020, 1, 1)) == 0
    assert months_between(date(2020, 6, 1), date(2020, 1, 1)) == -5


def test_a_role_covers_its_final_month():
    """'2015-08 -> 2017-12' means 29 months worked, December included."""
    assert _union_months(spans([job("2015-08-01", "2017-12-01")])) == 29


def test_december_to_january_crosses_the_year_correctly():
    assert _union_months(spans([job("2017-12-01", "2017-12-01")])) == 1


def test_consecutive_months_are_continuous_employment():
    """Leaving in December and starting in January is not a gap."""
    jobs = [
        job("2015-08-01", "2017-12-01"),
        job("2018-01-01", "2021-02-01"),
    ]
    assert max_gap_months(spans(jobs)) == 0
    assert max_overlap_months(spans(jobs)) == 0
    assert codes(jobs) == []


def test_a_current_role_runs_to_the_as_of_date():
    jobs = [job("2025-10-01", None, current=True)]
    assert _union_months(spans(jobs)) == 4  # Oct, Nov, Dec, Jan


# ── overlaps ──────────────────────────────────────────────────────────────
def test_a_shared_handover_month_is_tolerated():
    """One role ending and the next starting in the same month."""
    jobs = [
        job("2020-01-01", "2021-01-01"),
        job("2021-01-01", "2022-01-01"),
    ]
    assert max_overlap_months(spans(jobs)) == 0  # 1 month, within tolerance
    assert codes(jobs) == []


def test_two_month_overlap_is_a_possible_finding():
    jobs = [
        job("2020-01-01", "2021-02-01"),
        job("2021-01-01", "2022-01-01"),
    ]
    assert findings_by_name(jobs)["employment_overlap_minor"] == {
        "name": "employment_overlap_minor",
        "months": 2,
        "evidence": "suggestive",
    }
    assert timeline_confidence(find_timeline_issues(jobs, AS_OF), 2) == "possible"


def test_mid_sized_overlap_is_confirmed():
    jobs = [
        job("2020-01-01", "2021-06-01"),
        job("2021-01-01", "2022-01-01"),
    ]
    finding = findings_by_name(jobs)["employment_overlap"]
    assert (finding["months"], finding["evidence"]) == (6, "proven")


def test_long_overlap_is_severe():
    """The cv_089 shape: two full-time roles running for years at once."""
    jobs = [
        job("2012-07-01", "2021-01-01"),
        job("2016-03-01", "2021-03-01"),
        job("2021-01-01", None, seniority="Senior", current=True),
    ]
    finding = findings_by_name(jobs)["employment_overlap_severe"]
    assert (finding["months"], finding["evidence"]) == (59, "proven")
    assert timeline_confidence(find_timeline_issues(jobs, AS_OF), 3) == "not_confirmed"


def test_overlapping_months_are_counted_once():
    jobs = [
        job("2020-01-01", "2021-12-01"),
        job("2020-01-01", "2021-12-01"),
    ]
    assert _union_months(spans(jobs)) == 24


# ── gaps ──────────────────────────────────────────────────────────────────
def test_a_short_gap_is_not_flagged():
    jobs = [
        job("2020-01-01", "2020-12-01"),
        job("2021-04-01", "2022-01-01"),
    ]
    assert max_gap_months(spans(jobs)) == 3
    assert codes(jobs) == []


def test_gap_over_six_months_is_confirmed():
    jobs = [
        job("2020-01-01", "2020-12-01"),
        job("2021-09-01", "2022-01-01"),
    ]
    finding = findings_by_name(jobs)["long_gap"]
    assert (finding["months"], finding["evidence"]) == (8, "proven")


def test_very_long_gap_is_reported_separately():
    """The cv_119 shape: a seven-year hole in the timeline."""
    jobs = [
        job("2016-01-01", "2016-03-01", seniority="Intern"),
        job("2023-04-01", "2023-05-01"),
        job("2023-06-01", None, seniority="Junior", current=True),
    ]
    assert findings_by_name(jobs)["very_long_gap"]["months"] == 84
    assert "long_gap" not in codes(jobs)  # only the worse band is reported


def test_a_gap_inside_a_longer_role_is_not_a_gap():
    jobs = [
        job("2020-01-01", "2023-12-01"),
        job("2021-01-01", "2021-06-01"),
    ]
    assert max_gap_months(spans(jobs)) == 0


# ── seniority reached too fast ────────────────────────────────────────────
def test_a_moderate_shortfall_is_not_flagged():
    """
    The cv_141 shape: Staff Engineer with three years of prior experience.

    The published ladder puts Staff at seven years, so this is four years
    short - but a CV showing only three jobs cannot prove the earlier career
    is absent rather than merely unlisted. Below the six-year margin the claim
    is left unflagged rather than treated as dishonesty.
    """
    jobs = [
        job("2016-09-01", "2018-05-01", seniority="Graduate"),
        job("2018-06-01", "2019-08-01", seniority="Junior"),
        job("2023-01-01", None, seniority="Staff", current=True),
    ]
    assert seniority_shortfall_months(spans(jobs)) == 48  # 84 required, 36 held
    assert "seniority_implausible" not in codes(jobs)


def test_principal_in_a_first_job_is_flagged():
    """Principal is E6 on the ladder: eleven years, none of which are shown."""
    jobs = [job("2024-01-01", None, seniority="Principal", current=True)]
    finding = findings_by_name(jobs)["seniority_implausible"]
    assert (finding["months"], finding["evidence"]) == (132, "suggestive")


def test_the_shortfall_threshold_boundary():
    """Six years short is tolerated; beyond that it is flagged."""
    at_limit = [
        job("2023-01-01", "2023-12-01", seniority="Mid"),  # 12 months held
        job("2024-01-01", None, seniority="Staff", current=True),
    ]
    assert seniority_shortfall_months(spans(at_limit)) == 72  # 84 required
    assert "seniority_implausible" not in codes(at_limit)

    over_limit = [
        job("2023-02-01", "2023-12-01", seniority="Mid"),  # 11 months held
        job("2024-01-01", None, seniority="Staff", current=True),
    ]
    assert seniority_shortfall_months(spans(over_limit)) == 73
    assert "seniority_implausible" in codes(over_limit)


def test_enough_experience_is_not_flagged():
    jobs = [
        job("2015-01-01", "2018-12-01", seniority="Junior"),
        job("2019-01-01", None, seniority="Senior", current=True),
    ]
    # 48 months held against the 48 the ladder puts on Senior: no shortfall
    assert seniority_shortfall_months(spans(jobs)) == 0
    assert codes(jobs) == []


def test_levels_without_a_minimum_are_never_flagged():
    assert codes([job("2025-01-01", None, seniority=None, current=True)]) == []


def test_a_career_may_begin_at_an_entry_level_title():
    """
    E1-E2 titles carry no prior-experience requirement here: starting your
    career as a Junior with no earlier roles is normal, not a shortfall.
    """
    assert seniority_shortfall_months(
        spans([job("2025-01-01", None, seniority="Junior", current=True)])
    ) == 0
    assert seniority_shortfall_months(
        spans([job("2025-01-01", None, seniority="Graduate", current=True)])
    ) == 0


def test_a_senior_claim_cannot_fire_under_the_six_year_margin():
    """
    Stated consequence of the margin: the ladder puts Senior at four years, so
    even a Senior first job is only four years short and stays unflagged. That
    contradiction is the responsibility signal's to find, not the timeline's.
    """
    jobs = [job("2025-01-01", None, seniority="Senior", current=True)]
    assert seniority_shortfall_months(spans(jobs)) == 48
    assert "seniority_implausible" not in codes(jobs)


# ── multiple current roles ────────────────────────────────────────────────
def test_two_current_roles_are_flagged_without_a_month_measurement():
    jobs = [
        job("2022-01-01", None, current=True),
        job("2023-01-01", None, current=True),
    ]
    assert findings_by_name(jobs)["multiple_current_roles"] == {
        "name": "multiple_current_roles",
        "months": None,
        "evidence": "proven",
    }


# ── unevaluable rows ──────────────────────────────────────────────────────
def test_rows_without_a_start_date_are_reported_as_a_data_issue():
    jobs = [
        job("2020-01-01", "2021-12-01"),
        job(None, "2023-01-01"),
    ]
    finding = findings_by_name(jobs)["unevaluable_dates"]
    assert (finding["months"], finding["evidence"]) == (1, "data_issue")
    # a gap in the extraction must not condemn the candidate
    assert timeline_confidence(find_timeline_issues(jobs, AS_OF), 1) == "confirmed"


def test_a_candidate_with_no_usable_dates_is_not_evaluated():
    assert find_timeline_issues([job(None)], AS_OF) == []
    assert timeline_confidence([], 0) == "not_evaluated"


# ── status rule ───────────────────────────────────────────────────────────
def test_confidence_rule():
    proven = [{"name": "long_gap", "months": 8, "evidence": "proven"}]
    possible = [
        {"name": "employment_overlap_minor", "months": 2, "evidence": "suggestive"}
    ]
    data_issue = [
        {"name": "unevaluable_dates", "months": 1, "evidence": "data_issue"}
    ]

    assert timeline_confidence(proven + possible, 3) == "not_confirmed"
    assert timeline_confidence(possible, 3) == "possible"
    assert timeline_confidence(data_issue, 3) == "confirmed"
    assert timeline_confidence([], 3) == "confirmed"
    assert timeline_confidence(proven, 0) == "not_evaluated"


# ── whole-pipeline run against a fake warehouse ───────────────────────────
class FakeTimelineWarehouse:
    def __init__(self, work_experience):
        self._work_experience = work_experience
        self.written: list[dict] | None = None
        self.write_count = 0

    def read_work_experience(self):
        return self._work_experience

    def replace_signal(self, rows):
        self.written = rows
        self.write_count += 1


WORK_EXPERIENCE = [
    # clean: continuous, well-supported seniority
    job("2015-01-01", "2020-12-01", seniority="Junior", submission="cv_clean"),
    job("2021-01-01", None, seniority="Senior", current=True, submission="cv_clean"),
    # confirmed finding: years of overlap
    job("2015-01-01", "2020-12-01", submission="cv_overlap"),
    job("2017-01-01", "2020-12-01", submission="cv_overlap"),
    # possible finding only: two-month overlap
    job("2020-01-01", "2021-02-01", submission="cv_minor"),
    job("2021-01-01", "2022-01-01", submission="cv_minor"),
]


def _run():
    warehouse = FakeTimelineWarehouse(WORK_EXPERIENCE)
    result = run_signal_timeline_consistency(
        warehouse, now=lambda: EVALUATED_AT, as_of=AS_OF
    )
    return warehouse, result


def test_run_writes_one_row_per_candidate():
    warehouse, result = _run()

    assert warehouse.write_count == 1
    assert len(warehouse.written) == 3
    assert result["candidates"] == 3


def test_run_classifies_each_candidate():
    warehouse, result = _run()
    by_candidate = {row["submission_id"]: row for row in warehouse.written}

    assert by_candidate["cv_clean"]["confidence"] == "confirmed"
    assert by_candidate["cv_clean"]["findings"] == []

    assert by_candidate["cv_overlap"]["confidence"] == "not_confirmed"
    assert by_candidate["cv_overlap"]["findings"] == [
        {"name": "employment_overlap_severe", "months": 48, "evidence": "proven"}
    ]

    assert by_candidate["cv_minor"]["confidence"] == "possible"

    assert result["confidence"] == {"confirmed": 1, "not_confirmed": 1, "possible": 1}


def test_a_data_issue_alone_leaves_confidence_confirmed():
    rows = build_signal_rows(
        [
            job("2020-01-01", "2021-12-01", submission="cv_x"),
            job(None, "2023-01-01", submission="cv_x"),
        ],
        as_of=AS_OF,
        evaluated_at=EVALUATED_AT,
    )
    assert rows[0]["findings"][0]["name"] == "unevaluable_dates"
    assert rows[0]["confidence"] == "confirmed"


def test_run_records_the_as_of_date_and_timestamp():
    warehouse, result = _run()

    assert result["as_of_date"] == "2026-01-01"
    assert {row["as_of_date"] for row in warehouse.written} == {"2026-01-01"}
    assert {row["evaluated_at"] for row in warehouse.written} == {
        EVALUATED_AT.isoformat()
    }


def test_written_rows_match_the_bigquery_schema():
    warehouse, _ = _run()
    schema_fields = {field.name for field in SIGNAL_SCHEMA}
    finding_fields = {
        field.name
        for field in next(f for f in SIGNAL_SCHEMA if f.name == "findings").fields
    }

    for row in warehouse.written:
        assert set(row) == schema_fields
        for finding in row["findings"]:
            assert set(finding) == finding_fields


def test_build_signal_rows_is_pure():
    first = build_signal_rows(WORK_EXPERIENCE, as_of=AS_OF, evaluated_at=EVALUATED_AT)
    second = build_signal_rows(WORK_EXPERIENCE, as_of=AS_OF, evaluated_at=EVALUATED_AT)
    assert first == second
