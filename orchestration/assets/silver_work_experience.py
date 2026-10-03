"""
bronze.raw_work_experience -> silver.silver_work_experience

Structure: a pure core and a thin I/O shell.

    build_silver_work_experience_rows()  pure - the transformation, no BigQuery
    WorkExperienceWarehouse              protocol - every read/write needed
    BigQueryWorkExperienceWarehouse      the only code here touching BigQuery
    run_silver_work_experience()         orchestration, dependencies injected
    silver_work_experience               Dagster asset - wires the real ones

Because the warehouse is injected, the whole pipeline can be exercised against
an in-memory fake; see tests/test_silver_work_experience.py.
"""

import os
from collections import Counter
from datetime import datetime, timezone
from typing import Callable, Protocol

from dagster import asset, get_dagster_logger
from google.cloud import bigquery

from orchestration.assets.transformations import (
    WorkExperienceReference,
    build_work_experience_reference,
    transform_work_experience_row,
    work_experience_date_problems,
)

SILVER_WORK_EXPERIENCE_TABLE = "silver_work_experience"
SILVER_WORK_EXPERIENCE_SCHEMA = [
    bigquery.SchemaField("experience_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("submission_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("company_name", "STRING"),
    bigquery.SchemaField("job_title", "STRING"),
    bigquery.SchemaField("job_title_standardized", "STRING"),
    bigquery.SchemaField("seniority_level", "STRING"),
    bigquery.SchemaField("start_date", "DATE"),
    bigquery.SchemaField("end_date", "DATE"),
    bigquery.SchemaField("is_current", "BOOLEAN"),
    bigquery.SchemaField("location", "STRING"),
    bigquery.SchemaField("location_city", "STRING"),
    bigquery.SchemaField("location_country", "STRING"),
    bigquery.SchemaField("is_remote", "BOOLEAN"),
    bigquery.SchemaField("description", "STRING"),
    bigquery.SchemaField("company_website", "STRING"),
    bigquery.SchemaField("silver_processed_at", "TIMESTAMP", mode="REQUIRED"),
]

UNMATCHED_SAMPLE_SIZE = 10


# ── Pure core ─────────────────────────────────────────────────────────────
def build_silver_work_experience_rows(
    raw_rows: list[dict],
    reference: WorkExperienceReference,
    processed_at: datetime,
) -> list[dict]:
    """
    Transforms every bronze row into its silver row. Pure: the same inputs
    always give the same output, and nothing here reads or writes BigQuery.
    """
    timestamp = processed_at.isoformat()
    return [
        {**transform_work_experience_row(row, reference), "silver_processed_at": timestamp}
        for row in raw_rows
    ]


def summarize_gaps(silver_rows: list[dict], sample_size: int) -> dict:
    """
    What the transformation could not resolve, as counts plus the most
    frequent offenders. This is the maintenance signal: titles listed here
    belong in job_titles_review.csv, countries in location_aliases_review.csv.
    """
    missing_seniority = Counter(
        row["job_title"] for row in silver_rows if not row["seniority_level"]
    )
    missing_country = Counter(
        row["location"] for row in silver_rows if row["location"] and not row["location_country"]
    )
    date_problems: Counter = Counter()
    for row in silver_rows:
        date_problems.update(work_experience_date_problems(row))

    return {
        "rows_without_seniority": sum(missing_seniority.values()),
        "rows_without_country": sum(missing_country.values()),
        "date_problems": dict(date_problems),
        "top_titles_without_seniority": missing_seniority.most_common(sample_size),
        "top_locations_without_country": missing_country.most_common(sample_size),
    }


# ── I/O boundary ──────────────────────────────────────────────────────────
class WorkExperienceWarehouse(Protocol):
    """Everything the silver_work_experience pipeline needs from the warehouse."""

    def read_job_titles(self) -> list[dict]:
        """`dim_job_titles` rows: {job_title, seniority_level}."""

    def read_location_aliases(self) -> list[dict]:
        """`dim_location_aliases` rows: {location_token, country}."""

    def read_raw_work_experience(self) -> list[dict]:
        """`raw_work_experience` rows."""

    def replace_silver_work_experience(self, rows: list[dict]) -> None:
        """Replaces `silver_work_experience` with `rows`."""


class BigQueryWorkExperienceWarehouse:
    """WorkExperienceWarehouse backed by BigQuery."""

    def __init__(
        self,
        client: bigquery.Client | None = None,
        bronze_dataset: str | None = None,
        silver_dataset: str | None = None,
    ) -> None:
        self._client = client or bigquery.Client(project=os.getenv("GCP_PROJECT_ID"))
        self._bronze = bronze_dataset or os.getenv("BQ_DATASET_BRONZE")
        self._silver = silver_dataset or os.getenv("BQ_DATASET_SILVER")

    def _table(self, dataset: str, table: str) -> str:
        return f"{self._client.project}.{dataset}.{table}"

    def _rows(self, query: str) -> list[dict]:
        return [dict(row) for row in self._client.query(query).result()]

    def read_job_titles(self) -> list[dict]:
        return self._rows(
            f"SELECT job_title, seniority_level "
            f"FROM `{self._table(self._silver, 'dim_job_titles')}`"
        )

    def read_location_aliases(self) -> list[dict]:
        return self._rows(
            f"SELECT location_token, country "
            f"FROM `{self._table(self._silver, 'dim_location_aliases')}`"
        )

    def read_raw_work_experience(self) -> list[dict]:
        return self._rows(f"""
            SELECT experience_id, submission_id, company_name, job_title,
                   start_date_raw, end_date_raw, is_current, location,
                   description, company_website
            FROM `{self._table(self._bronze, 'raw_work_experience')}`
        """)

    def replace_silver_work_experience(self, rows: list[dict]) -> None:
        """
        Full refresh: bronze is the source of truth, so silver is rebuilt from
        it rather than appended to (no duplicate or stale rows on reruns).
        """
        job_config = bigquery.LoadJobConfig(
            schema=SILVER_WORK_EXPERIENCE_SCHEMA,
            write_disposition="WRITE_TRUNCATE",
        )
        self._client.load_table_from_json(
            rows,
            self._table(self._silver, SILVER_WORK_EXPERIENCE_TABLE),
            job_config=job_config,
        ).result()


# ── Orchestration (dependencies injected) ─────────────────────────────────
def run_silver_work_experience(
    warehouse: WorkExperienceWarehouse,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    report: Callable[[str], None] = lambda message: None,
) -> dict:
    """
    Reads bronze and the reference tables, transforms, writes silver, and
    returns run metadata. The warehouse, clock and reporter are injected so
    this runs with no BigQuery and no Dagster.
    """
    reference = build_work_experience_reference(
        warehouse.read_job_titles(),
        warehouse.read_location_aliases(),
    )
    report(
        f"Reference: {len(reference.seniority_by_title)} titles with a seniority level, "
        f"{len(reference.country_by_location_token)} location aliases"
    )

    raw_rows = warehouse.read_raw_work_experience()
    report(f"Read {len(raw_rows)} rows from raw_work_experience")

    silver_rows = build_silver_work_experience_rows(raw_rows, reference, now())
    warehouse.replace_silver_work_experience(silver_rows)
    report(f"Loaded {len(silver_rows)} rows into {SILVER_WORK_EXPERIENCE_TABLE}")

    gaps = summarize_gaps(silver_rows, UNMATCHED_SAMPLE_SIZE)
    report(
        f"No seniority level: {gaps['rows_without_seniority']} rows | "
        f"No country: {gaps['rows_without_country']} rows | "
        f"Date problems: {gaps['date_problems'] or 'none'}"
    )
    if gaps["top_locations_without_country"]:
        report(
            "Add these to location_aliases_review.csv: "
            f"{gaps['top_locations_without_country']}"
        )

    return {
        "work_experience_count": len(silver_rows),
        "distinct_submissions": len({row["submission_id"] for row in silver_rows}),
        "current_roles": sum(1 for row in silver_rows if row["is_current"]),
        "remote_roles": sum(1 for row in silver_rows if row["is_remote"]),
        **gaps,
    }


# ── ASSET: silver_work_experience ─────────────────────────────────────────
@asset(deps=["extract_entities"])
def silver_work_experience():
    """
    Standardizes bronze raw_work_experience into silver_work_experience.

    - company_name / job_title / location / description: preserved as written
    - job_title_standardized: punctuation replaced by spaces
      ("Staff Engineer - Cloud Infrastructure" -> "Staff Engineer Cloud Infrastructure")
    - seniority_level: from dim_job_titles, NULL when the title states no level
    - start_date / end_date: parsed to DATE at month precision;
      "Present" -> end_date NULL with is_current true
    - location_city / location_country / is_remote: split from location, with
      country aliases resolved through dim_location_aliases
      (UK, Scotland, Northern Ireland -> United Kingdom)

    Load the reference tables first:
        python -m ingestion.load_dim_job_titles
        python -m ingestion.load_dim_location_aliases
    """
    return run_silver_work_experience(
        BigQueryWorkExperienceWarehouse(),
        report=get_dagster_logger().info,
    )
