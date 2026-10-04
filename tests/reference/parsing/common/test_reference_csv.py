"""
Tests for the row reader the flat dimension CSVs share: required columns, and
a key that must be present and unique.
"""

import pytest

from reference.parsing.common.reference_csv import ReferenceDataError, read_csv_rows

COLUMNS = ["job_title", "seniority_level"]


def test_parse_returns_stripped_rows_limited_to_required_columns():
    text = "job_title,seniority_level,notes\n  Staff Engineer , Staff ,whatever\n"

    assert read_csv_rows(
        text, required_columns=COLUMNS, key_column="job_title"
    ) == [{"job_title": "Staff Engineer", "seniority_level": "Staff"}]


def test_parse_rejects_missing_column():
    with pytest.raises(ReferenceDataError, match="missing columns"):
        read_csv_rows(
            "title,level\nStaff Engineer,Staff\n",
            required_columns=COLUMNS,
            key_column="job_title",
        )


def test_parse_rejects_blank_key():
    with pytest.raises(ReferenceDataError, match="blank job_title"):
        read_csv_rows(
            "job_title,seniority_level\n,Staff\n",
            required_columns=COLUMNS,
            key_column="job_title",
        )


def test_parse_rejects_duplicate_key():
    text = "job_title,seniority_level\nStaff Engineer,Staff\nStaff Engineer,Senior\n"
    with pytest.raises(ReferenceDataError, match="duplicate job_title"):
        read_csv_rows(text, required_columns=COLUMNS, key_column="job_title")


def test_parse_rejects_a_file_with_no_rows():
    with pytest.raises(ReferenceDataError, match="no rows"):
        read_csv_rows(
            "job_title,seniority_level\n",
            required_columns=COLUMNS,
            key_column="job_title",
        )
