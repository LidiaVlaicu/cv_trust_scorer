"""
Tests for the job titles dimension, including golden checks against the real
review file so an accidental edit to it fails loudly.
"""

import pytest

from reference import JOB_TITLES_CSV
from reference.parsing.dim_job_titles import parse_job_titles, to_bigquery_rows
from silver.rules.work_experience import (
    build_work_experience_reference,
    standardize_job_title,
)


def _reviewed() -> list[dict]:
    return parse_job_titles(JOB_TITLES_CSV.read_text(encoding="utf-8"))


def _reference():
    return build_work_experience_reference(_reviewed(), [])


# ── row shaping ───────────────────────────────────────────────────────────
def test_a_blank_level_becomes_null_not_an_empty_string():
    rows = to_bigquery_rows(
        [
            {"job_title": "Staff Engineer", "seniority_level": "Staff"},
            {"job_title": "Data Analyst", "seniority_level": ""},
        ]
    )

    assert rows == [
        {"job_title": "Staff Engineer", "seniority_level": "Staff"},
        {"job_title": "Data Analyst", "seniority_level": None},
    ]


# ── golden checks on the real review file ─────────────────────────────────
def test_the_real_file_parses_and_builds_a_conflict_free_reference():
    titles = _reviewed()
    reference = build_work_experience_reference(titles, [])

    assert len(titles) == 181
    # 42 of the 181 titles state no level, so they carry no entry
    assert len(reference.seniority_by_title) == 139


def test_review_file_standardized_column_matches_the_code():
    """
    The CSV carries job_title_standardized for review only; it is not loaded.
    If it ever disagrees with the function, one of the two is wrong.
    """
    from reference.parsing.common.reference_csv import read_csv_rows

    rows = read_csv_rows(
        JOB_TITLES_CSV.read_text(encoding="utf-8"),
        required_columns=["job_title", "job_title_standardized"],
        key_column="job_title",
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
    assert _reference().seniority_for(job_title) == expected_seniority
