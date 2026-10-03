"""
Loads the reviewed job titles into the `dim_job_titles` reference table.

    job_titles_review.csv  (reviewed, version-controlled)
              |
              v  parse + validate (pure, see reference_csv.py)
       silver.dim_job_titles   (job_title -> seniority_level)

Full refresh: the CSV is the single source of truth, so the table is replaced
with exactly what the file says. An incremental merge would leave titles from
an earlier version of the file behind, still carrying a seniority the reviewer
has since changed.

The CSV's `job_title_standardized` column is deliberately NOT loaded. That
value is produced by `transformations.standardize_job_title` at transform time,
so the rule lives in exactly one place; the column exists in the file only so
the standardization could be reviewed alongside the seniority.

Run with:  python -m reference.loaders.dim_job_titles
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery

from reference import JOB_TITLES_CSV
from reference.parsing.reference_csv import parse_reference_csv

load_dotenv()

JOB_TITLES_CSV_PATH = JOB_TITLES_CSV

DIM_JOB_TITLES_TABLE = "dim_job_titles"
DIM_JOB_TITLES_SCHEMA = [
    bigquery.SchemaField("job_title", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("seniority_level", "STRING"),
]


def load_dim_job_titles(csv_path: Path = JOB_TITLES_CSV_PATH) -> int:
    """Replaces `dim_job_titles` with the titles in `csv_path`. Returns the row count."""
    reviewed = parse_reference_csv(
        csv_path.read_text(encoding="utf-8"),
        required_columns=["job_title", "seniority_level"],
        key_column="job_title",
    )

    rows = [
        {
            "job_title": entry["job_title"],
            # a blank cell means "the title states no level" -> NULL, not ""
            "seniority_level": entry["seniority_level"] or None,
        }
        for entry in reviewed
    ]

    client = bigquery.Client(project=os.getenv("GCP_PROJECT_ID"))
    table_id = f"{client.project}.{os.getenv('BQ_DATASET_SILVER')}.{DIM_JOB_TITLES_TABLE}"

    job_config = bigquery.LoadJobConfig(
        schema=DIM_JOB_TITLES_SCHEMA,
        write_disposition="WRITE_TRUNCATE",
    )
    client.load_table_from_json(rows, table_id, job_config=job_config).result()

    with_level = sum(1 for row in rows if row["seniority_level"])
    print(
        f"Loaded {len(rows)} job titles into {table_id} "
        f"({with_level} with a seniority level, {len(rows) - with_level} without)"
    )
    return len(rows)


if __name__ == "__main__":
    load_dim_job_titles()
