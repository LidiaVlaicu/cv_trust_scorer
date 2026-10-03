"""
Tests for the pure work-experience transforms: job title standardization,
CV date parsing and location splitting.

The reference lookups are injected, so none of this needs BigQuery.
"""

from datetime import date

import pytest

from orchestration.assets.transformations import (
    build_work_experience_reference,
    parse_cv_month,
    split_location,
    standardize_job_title,
    transform_work_experience_row,
    work_experience_date_problems,
)

JOB_TITLE_ROWS = [
    {"job_title": "Senior Software Engineer - Backend Systems", "seniority_level": "Senior"},
    {"job_title": "Software Engineer (Junior)", "seniority_level": "Junior"},
    {"job_title": "Staff Engineer - Cloud Infrastructure", "seniority_level": "Staff"},
    {"job_title": "Data Analyst", "seniority_level": None},
    {"job_title": "Graduate Software Engineer", "seniority_level": "Graduate"},
]

LOCATION_ALIAS_ROWS = [
    {"location_token": "United Kingdom", "country": "United Kingdom"},
    {"location_token": "UK", "country": "United Kingdom"},
    {"location_token": "Scotland", "country": "United Kingdom"},
    {"location_token": "Northern Ireland", "country": "United Kingdom"},
    {"location_token": "Ireland", "country": "Ireland"},
    {"location_token": "Sweden", "country": "Sweden"},
    {"location_token": "Stockholm", "country": "Sweden"},
]

REFERENCE = build_work_experience_reference(JOB_TITLE_ROWS, LOCATION_ALIAS_ROWS)


# ── job title standardization ─────────────────────────────────────────────
def test_standardize_job_title_replaces_every_non_word_character():
    assert (
        standardize_job_title("Staff Engineer - Cloud Infrastructure")
        == "Staff Engineer Cloud Infrastructure"
    )
    assert standardize_job_title("Software Engineer (Junior)") == "Software Engineer Junior"
    assert standardize_job_title("Research Engineer, Staff") == "Research Engineer Staff"
    assert standardize_job_title("Mid-Level Data Analyst") == "Mid Level Data Analyst"
    assert standardize_job_title("Data Analyst (Placement Year)") == "Data Analyst Placement Year"


def test_standardize_job_title_collapses_whitespace_and_handles_empty():
    assert standardize_job_title("  Senior   Data  Engineer ") == "Senior Data Engineer"
    assert standardize_job_title("") == ""


def test_standardize_job_title_merges_the_separator_twins():
    """The two titles that differ only by '-' versus ',' must come out equal."""
    assert standardize_job_title("Senior Backend Engineer - Platform Team") == standardize_job_title(
        "Senior Backend Engineer, Platform Team"
    )


def test_standardize_job_title_keeps_digits():
    assert standardize_job_title("Research Engineer II") == "Research Engineer II"


# ── date parsing ──────────────────────────────────────────────────────────
def test_parse_cv_month_accepts_both_formats_in_the_data():
    assert parse_cv_month("August 2017") == (date(2017, 8, 1), False)
    assert parse_cv_month("Jul 2021") == (date(2021, 7, 1), False)


def test_parse_cv_month_recognises_current_markers():
    assert parse_cv_month("Present") == (None, True)
    assert parse_cv_month("present") == (None, True)
    assert parse_cv_month("Current") == (None, True)


def test_parse_cv_month_returns_none_for_empty_or_unparseable():
    assert parse_cv_month("") == (None, False)
    assert parse_cv_month(None) == (None, False)
    assert parse_cv_month("sometime in 2017") == (None, False)


# ── location splitting ────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "location, expected",
    [
        ("Dublin, Ireland", ("Dublin", "Ireland", False)),
        ("Edinburgh, UK", ("Edinburgh", "United Kingdom", False)),
        ("Edinburgh, Scotland", ("Edinburgh", "United Kingdom", False)),
        ("Belfast, Northern Ireland", ("Belfast", "United Kingdom", False)),
        ("Canary Wharf, London, United Kingdom", ("London", "United Kingdom", False)),
        ("Remote / Edinburgh, United Kingdom", ("Edinburgh", "United Kingdom", True)),
        ("Stockholm Office, Sweden", ("Stockholm", "Sweden", False)),
        ("Stockholm", ("Stockholm", "Sweden", False)),
        ("Sweden", (None, "Sweden", False)),
        ("", (None, None, False)),
        ("Paris, France", ("Paris", None, False)),  # France not in this fixture
    ],
)
def test_split_location(location, expected):
    assert split_location(location, REFERENCE) == expected


def test_split_location_keeps_ireland_and_northern_ireland_apart():
    _, republic, _ = split_location("Dublin, Ireland", REFERENCE)
    _, north, _ = split_location("Belfast, Northern Ireland", REFERENCE)
    assert republic == "Ireland"
    assert north == "United Kingdom"


# ── reference building ────────────────────────────────────────────────────
def test_reference_lookup_is_case_insensitive():
    assert REFERENCE.seniority_for("data analyst") is None
    assert REFERENCE.seniority_for("GRADUATE SOFTWARE ENGINEER") == "Graduate"
    assert REFERENCE.country_for("uk") == "United Kingdom"


def test_build_reference_rejects_conflicting_job_titles():
    with pytest.raises(ValueError, match="Conflicting job title reference"):
        build_work_experience_reference(
            [
                {"job_title": "Staff Engineer", "seniority_level": "Staff"},
                {"job_title": "staff engineer", "seniority_level": "Senior"},
            ],
            LOCATION_ALIAS_ROWS,
        )


def test_build_reference_rejects_conflicting_location_tokens():
    with pytest.raises(ValueError, match="Conflicting location reference"):
        build_work_experience_reference(
            JOB_TITLE_ROWS,
            [
                {"location_token": "Scotland", "country": "United Kingdom"},
                {"location_token": "scotland", "country": "Scotland"},
            ],
        )


# ── full row ──────────────────────────────────────────────────────────────
def test_transform_work_experience_row_end_to_end():
    row = {
        "experience_id": "cv_001_job2",
        "submission_id": "cv_001",
        "company_name": "TechVault Solutions Ltd",
        "job_title": "Senior Software Engineer - Backend Systems",
        "start_date_raw": "August 2019",
        "end_date_raw": "April 2022",
        "is_current": False,
        "location": "London, United Kingdom",
        "description": "Built things.",
        "company_website": "techvault.co.net",
    }

    assert transform_work_experience_row(row, REFERENCE) == {
        "experience_id": "cv_001_job2",
        "submission_id": "cv_001",
        "company_name": "TechVault Solutions Ltd",
        "job_title": "Senior Software Engineer - Backend Systems",
        "job_title_standardized": "Senior Software Engineer Backend Systems",
        "seniority_level": "Senior",
        "start_date": "2019-08-01",
        "end_date": "2022-04-01",
        "is_current": False,
        "location": "London, United Kingdom",
        "location_city": "London",
        "location_country": "United Kingdom",
        "is_remote": False,
        "description": "Built things.",
        "company_website": "techvault.co.net",
    }


def test_transform_work_experience_row_current_role():
    row = {
        "experience_id": "cv_002_job1",
        "submission_id": "cv_002",
        "company_name": "DataFlow Systems",
        "job_title": "Data Analyst",
        "start_date_raw": "March 2021",
        "end_date_raw": "Present",
        "is_current": True,
        "location": "Remote / Edinburgh, United Kingdom",
        "description": None,
        "company_website": None,
    }

    result = transform_work_experience_row(row, REFERENCE)

    assert result["start_date"] == "2021-03-01"
    assert result["end_date"] is None
    assert result["is_current"] is True
    assert result["seniority_level"] is None  # the title states no level
    assert result["is_remote"] is True
    assert result["location_city"] == "Edinburgh"


def test_transform_work_experience_row_keeps_unknowns_as_none():
    row = {
        "experience_id": "cv_003_job1",
        "submission_id": "cv_003",
        "company_name": "Some Startup",
        "job_title": "Chief Vibes Officer",
        "start_date_raw": "whenever",
        "end_date_raw": "later",
        "is_current": False,
        "location": "Atlantis, Oceania",
        "description": None,
        "company_website": None,
    }

    result = transform_work_experience_row(row, REFERENCE)

    assert result["job_title"] == "Chief Vibes Officer"  # kept
    assert result["seniority_level"] is None
    assert result["start_date"] is None
    assert result["end_date"] is None
    assert result["location_city"] == "Atlantis"
    assert result["location_country"] is None


# ── date validation ───────────────────────────────────────────────────────
def test_date_problems_flags_reversed_range():
    row = {"start_date": "2020-05-01", "end_date": "2019-01-01", "is_current": False}
    assert "start_after_end" in work_experience_date_problems(row)


def test_date_problems_flags_unparsed_and_future_and_implausible():
    assert "unparsed_start_date" in work_experience_date_problems(
        {"start_date": None, "end_date": "2020-01-01", "is_current": False}
    )
    assert "unparsed_end_date" in work_experience_date_problems(
        {"start_date": "2020-01-01", "end_date": None, "is_current": False}
    )
    assert "date_in_future" in work_experience_date_problems(
        {"start_date": "2020-01-01", "end_date": "2999-01-01", "is_current": False}
    )
    assert "implausible_year" in work_experience_date_problems(
        {"start_date": "1870-01-01", "end_date": "1880-01-01", "is_current": False}
    )


def test_date_problems_accepts_a_current_role_without_end_date():
    row = {"start_date": "2021-03-01", "end_date": None, "is_current": True}
    assert work_experience_date_problems(row) == []
