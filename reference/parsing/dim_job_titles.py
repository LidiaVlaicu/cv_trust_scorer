"""
Parses and validates `job_titles_review.csv` into `dim_job_titles` rows.

    job_title -> seniority_level

`job_title_standardized` is deliberately not loaded. That value is produced by
`standardize_job_title` at transform time, so the rule lives in one place; the
column exists in the file only so the standardization could be reviewed
alongside the seniority.
"""

from reference.parsing.common.reference_csv import read_csv_rows

REQUIRED_COLUMNS = ["job_title", "seniority_level"]
KEY_COLUMN = "job_title"


def parse_job_titles(csv_text: str) -> list[dict]:
    """The reviewed rows: {job_title, seniority_level}."""
    return read_csv_rows(
        csv_text,
        required_columns=REQUIRED_COLUMNS,
        key_column=KEY_COLUMN,
    )


def to_bigquery_rows(reviewed: list[dict]) -> list[dict]:
    """Shapes reviewed rows as `dim_job_titles` rows."""
    return [
        {
            "job_title": entry["job_title"],
            # a blank cell means "the title states no level" -> NULL, not ""
            "seniority_level": entry["seniority_level"] or None,
        }
        for entry in reviewed
    ]
