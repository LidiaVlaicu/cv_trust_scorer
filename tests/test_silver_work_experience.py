"""
End-to-end test of the silver_work_experience pipeline against an in-memory
fake warehouse — no BigQuery, no Dagster, no credentials.
"""

from datetime import datetime, timezone

from orchestration.assets.silver_work_experience import (
    SILVER_WORK_EXPERIENCE_SCHEMA,
    build_silver_work_experience_rows,
    run_silver_work_experience,
    summarize_gaps,
)
from orchestration.assets.transformations import build_work_experience_reference

FIXED_TIME = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

JOB_TITLE_ROWS = [
    {"job_title": "Senior Backend Engineer", "seniority_level": "Senior"},
    {"job_title": "Data Analyst", "seniority_level": None},
    {"job_title": "Junior Data Engineer", "seniority_level": "Junior"},
]

LOCATION_ALIAS_ROWS = [
    {"location_token": "United Kingdom", "country": "United Kingdom"},
    {"location_token": "Scotland", "country": "United Kingdom"},
    {"location_token": "Sweden", "country": "Sweden"},
]

RAW_ROWS = [
    {
        "experience_id": "cv_1_job1",
        "submission_id": "cv_1",
        "company_name": "DataFlow Systems Ltd",
        "job_title": "Senior Backend Engineer",
        "start_date_raw": "March 2021",
        "end_date_raw": "Present",
        "is_current": True,
        "location": "Edinburgh, Scotland",
        "description": "Built pipelines.",
        "company_website": "dataflow.co",
    },
    {
        "experience_id": "cv_1_job2",
        "submission_id": "cv_1",
        "company_name": "Nordic Analytics AB",
        "job_title": "Junior Data Engineer",
        "start_date_raw": "Jul 2018",
        "end_date_raw": "Feb 2021",
        "is_current": False,
        "location": "Stockholm Office, Sweden",
        "description": None,
        "company_website": None,
    },
    {
        "experience_id": "cv_2_job1",
        "submission_id": "cv_2",
        "company_name": "Insight Partners",
        "job_title": "Data Analyst",
        "start_date_raw": "January 2019",
        "end_date_raw": "June 2020",
        "is_current": False,
        "location": "Lyon, France",  # France is absent from the fixture
        "description": None,
        "company_website": None,
    },
]


class FakeWorkExperienceWarehouse:
    """In-memory WorkExperienceWarehouse. Records what would be written."""

    def __init__(self, job_titles, location_aliases, raw_rows) -> None:
        self._job_titles = job_titles
        self._location_aliases = location_aliases
        self._raw_rows = raw_rows
        self.written: list[dict] | None = None
        self.write_count = 0

    def read_job_titles(self) -> list[dict]:
        return self._job_titles

    def read_location_aliases(self) -> list[dict]:
        return self._location_aliases

    def read_raw_work_experience(self) -> list[dict]:
        return self._raw_rows

    def replace_silver_work_experience(self, rows: list[dict]) -> None:
        self.written = rows
        self.write_count += 1


def _run():
    warehouse = FakeWorkExperienceWarehouse(JOB_TITLE_ROWS, LOCATION_ALIAS_ROWS, RAW_ROWS)
    result = run_silver_work_experience(warehouse, now=lambda: FIXED_TIME)
    return warehouse, result


def test_writes_one_silver_row_per_bronze_row():
    warehouse, result = _run()

    assert warehouse.write_count == 1
    assert len(warehouse.written) == len(RAW_ROWS)
    assert result["work_experience_count"] == len(RAW_ROWS)
    assert result["distinct_submissions"] == 2


def test_transforms_each_row():
    warehouse, _ = _run()
    by_id = {row["experience_id"]: row for row in warehouse.written}

    current = by_id["cv_1_job1"]
    assert current["start_date"] == "2021-03-01"
    assert current["end_date"] is None
    assert current["is_current"] is True
    assert current["seniority_level"] == "Senior"
    assert current["location_city"] == "Edinburgh"
    assert current["location_country"] == "United Kingdom"

    past = by_id["cv_1_job2"]
    assert past["start_date"] == "2018-07-01"
    assert past["end_date"] == "2021-02-01"
    assert past["location_city"] == "Stockholm"
    assert past["seniority_level"] == "Junior"


def test_unknown_country_and_missing_seniority_are_null_not_dropped():
    warehouse, result = _run()
    unknown = next(r for r in warehouse.written if r["experience_id"] == "cv_2_job1")

    assert unknown["location"] == "Lyon, France"  # preserved
    assert unknown["location_city"] == "Lyon"
    assert unknown["location_country"] is None
    assert unknown["seniority_level"] is None

    assert result["rows_without_country"] == 1
    assert result["top_locations_without_country"] == [("Lyon, France", 1)]
    assert result["rows_without_seniority"] == 1


def test_reports_current_and_remote_counts_and_no_date_problems():
    _, result = _run()

    assert result["current_roles"] == 1
    assert result["remote_roles"] == 0
    assert result["date_problems"] == {}


def test_written_rows_match_the_bigquery_schema():
    """Guards against a column added to the transform but not the schema."""
    warehouse, _ = _run()
    schema_fields = {field.name for field in SILVER_WORK_EXPERIENCE_SCHEMA}

    for row in warehouse.written:
        assert set(row) == schema_fields


def test_every_row_carries_the_injected_timestamp():
    warehouse, _ = _run()
    assert {row["silver_processed_at"] for row in warehouse.written} == {
        FIXED_TIME.isoformat()
    }


def test_build_rows_is_pure():
    reference = build_work_experience_reference(JOB_TITLE_ROWS, LOCATION_ALIAS_ROWS)

    first = build_silver_work_experience_rows(RAW_ROWS, reference, FIXED_TIME)
    second = build_silver_work_experience_rows(RAW_ROWS, reference, FIXED_TIME)

    assert first == second


def test_summarize_gaps_counts_date_problems():
    rows = [
        {
            "job_title": "Data Analyst",
            "seniority_level": None,
            "location": "Lyon, France",
            "location_country": None,
            "start_date": "2020-05-01",
            "end_date": "2019-01-01",
            "is_current": False,
        }
    ]

    gaps = summarize_gaps(rows, 10)

    assert gaps["rows_without_seniority"] == 1
    assert gaps["rows_without_country"] == 1
    assert gaps["date_problems"] == {"start_after_end": 1}
