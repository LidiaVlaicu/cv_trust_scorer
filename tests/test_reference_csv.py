"""
Tests for the reviewed-reference-CSV parser, plus golden checks against the
real review files so an accidental edit to them fails loudly.
"""

from pathlib import Path

import pytest

from reference import JOB_TITLES_CSV, LOCATION_ALIASES_CSV
from reference.parsing.reference_csv import ReferenceDataError, parse_reference_csv
from orchestration.assets.transformations import (
    build_work_experience_reference,
    standardize_job_title,
)


def _parse(path: Path, required_columns: list[str], key_column: str) -> list[dict]:
    return parse_reference_csv(
        path.read_text(encoding="utf-8"),
        required_columns=required_columns,
        key_column=key_column,
    )


# ── parser behaviour ──────────────────────────────────────────────────────
def test_parse_returns_stripped_rows_limited_to_required_columns():
    text = "job_title,seniority_level,notes\n  Staff Engineer , Staff ,whatever\n"

    assert parse_reference_csv(
        text, required_columns=["job_title", "seniority_level"], key_column="job_title"
    ) == [{"job_title": "Staff Engineer", "seniority_level": "Staff"}]


def test_parse_rejects_missing_column():
    with pytest.raises(ReferenceDataError, match="missing columns"):
        parse_reference_csv(
            "title,level\nStaff Engineer,Staff\n",
            required_columns=["job_title", "seniority_level"],
            key_column="job_title",
        )


def test_parse_rejects_blank_key():
    with pytest.raises(ReferenceDataError, match="blank job_title"):
        parse_reference_csv(
            "job_title,seniority_level\n,Staff\n",
            required_columns=["job_title", "seniority_level"],
            key_column="job_title",
        )


def test_parse_rejects_duplicate_key():
    text = "job_title,seniority_level\nStaff Engineer,Staff\nStaff Engineer,Senior\n"
    with pytest.raises(ReferenceDataError, match="duplicate job_title"):
        parse_reference_csv(
            text, required_columns=["job_title", "seniority_level"], key_column="job_title"
        )


def test_parse_rejects_a_file_with_no_rows():
    with pytest.raises(ReferenceDataError, match="no rows"):
        parse_reference_csv(
            "job_title,seniority_level\n",
            required_columns=["job_title", "seniority_level"],
            key_column="job_title",
        )


# ── golden checks on the real reviewed files ──────────────────────────────
def test_real_review_files_parse_and_build_a_conflict_free_reference():
    titles = _parse(JOB_TITLES_CSV, ["job_title", "seniority_level"], "job_title")
    aliases = _parse(LOCATION_ALIASES_CSV, ["location_token", "country"], "location_token")

    reference = build_work_experience_reference(titles, aliases)

    assert len(titles) == 181
    assert len(aliases) == 15
    # 42 of the 181 titles state no level, so they carry no entry
    assert len(reference.seniority_by_title) == 139
    assert len(reference.country_by_location_token) == 15


def test_every_location_alias_has_a_country():
    aliases = _parse(LOCATION_ALIASES_CSV, ["location_token", "country"], "location_token")
    assert [a["location_token"] for a in aliases if not a["country"]] == []


def test_review_file_standardized_column_matches_the_code():
    """
    The CSV carries job_title_standardized for review only; it is not loaded.
    If it ever disagrees with the function, one of the two is wrong.
    """
    rows = _parse(
        JOB_TITLES_CSV,
        ["job_title", "job_title_standardized"],
        "job_title",
    )
    mismatched = [
        (r["job_title"], r["job_title_standardized"], standardize_job_title(r["job_title"]))
        for r in rows
        if standardize_job_title(r["job_title"]) != r["job_title_standardized"]
    ]
    assert mismatched == []


@pytest.mark.parametrize(
    "job_title, expected_seniority",
    [
        ("Senior Software Engineer", "Senior"),
        ("Junior Data Engineer", "Junior"),
        ("Staff Engineer - Cloud Infrastructure", "Staff"),
        ("Graduate Software Engineer", "Graduate"),
        ("Software Engineer (Junior)", "Junior"),
        ("Research Engineer, Staff", "Staff"),
        ("Research Engineer II", "Mid"),
        ("Junior DevOps Apprentice", "Apprentice"),
        ("Junior Developer Intern", "Intern"),
        ("Principal Data Science Director", "Director"),
        ("Engineering Manager", "Manager"),
        ("Lead Software Engineer", "Lead"),
        # titles that state no level must stay unassigned
        ("Data Analyst", None),
        ("Backend Engineer", None),
        ("Software Engineer", None),
        ("Infrastructure Associate", None),
    ],
)
def test_reviewed_seniority_golden_examples(job_title, expected_seniority):
    titles = _parse(JOB_TITLES_CSV, ["job_title", "seniority_level"], "job_title")
    aliases = _parse(LOCATION_ALIASES_CSV, ["location_token", "country"], "location_token")
    reference = build_work_experience_reference(titles, aliases)

    assert reference.seniority_for(job_title) == expected_seniority


@pytest.mark.parametrize(
    "location_token, expected_country",
    [
        ("United Kingdom", "United Kingdom"),
        ("UK", "United Kingdom"),
        ("Scotland", "United Kingdom"),
        ("Northern Ireland", "United Kingdom"),
        ("Ireland", "Ireland"),
        ("Stockholm", "Sweden"),
        ("Västerås", "Sweden"),
    ],
)
def test_reviewed_country_golden_examples(location_token, expected_country):
    titles = _parse(JOB_TITLES_CSV, ["job_title", "seniority_level"], "job_title")
    aliases = _parse(LOCATION_ALIASES_CSV, ["location_token", "country"], "location_token")
    reference = build_work_experience_reference(titles, aliases)

    assert reference.country_for(location_token) == expected_country
