"""
BigQuery persistence layer for the Bronze dataset.

Provides functions to insert, retrieve, and delete resume data stored
in the Bronze tables. It also implements the change-detection logic used to
keep the ingestion pipeline idempotent by skipping unchanged resumes and
removing outdated records before reprocessing.
"""

import os

from dotenv import load_dotenv
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

load_dotenv()

PROJECT_ID = os.environ["GCP_PROJECT_ID"]
BRONZE_DATASET = os.environ["BQ_DATASET_BRONZE"]

# ── BigQuery helpers ──────────────────────────────────────────────────────
def insert_rows_to_bigquery(table_id, rows):
    """Inserts a list of rows into a BigQuery table."""
    client = bigquery.Client(project=PROJECT_ID)
    errors = client.insert_rows_json(table_id, rows)
    if errors:
        raise Exception(f"BigQuery insert errors: {errors}")


def delete_cv_data(submission_id: str):
    """
    Removes all bronze records for a given submission_id.
    Uses parameterized SQL to avoid injection on names with apostrophes.
    """
    client = bigquery.Client(project=PROJECT_ID)
    tables = ["raw_cv_texts", "raw_candidates", "raw_work_experience", "raw_skills"]

    for table in tables:
        query = f"""
            DELETE FROM `{PROJECT_ID}.{BRONZE_DATASET}.{table}`
            WHERE submission_id = @submission_id
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("submission_id", "STRING", submission_id),
            ]
        )
        client.query(query, job_config=job_config).result()

def get_processed_versions(table, id_col="submission_id", hash_col="content_hash"):
    """
    Returns {submission_id: content_hash} of already-processed CVs.
    Returns empty dict if the table doesn't exist yet (first run).
    Only call this for tables that actually have a `hash_col` column
    (currently just raw_cv_texts) — see get_processed_submission_ids for
    tables without a hash column.
    """
    client = bigquery.Client(project=PROJECT_ID)
    query = f"""
        SELECT {id_col}, {hash_col}
        FROM `{PROJECT_ID}.{BRONZE_DATASET}.{table}`
    """
    try:
        rows = client.query(query).result()
        return {row[id_col]: row[hash_col] for row in rows}
    except NotFound:
        return {}


def get_all_cv_texts():
    """
    Returns every row currently in raw_cv_texts, queried fresh from BigQuery.

    Used as the input source for extract_entities instead of the
    extract_raw_text Dagster input, because that input is only whatever
    extract_raw_text happened to return on its *last* run (newly-processed
    CVs only) — not the full current set. Querying the table directly means
    extract_entities always sees the real, current list of CVs.
    """
    client = bigquery.Client(project=PROJECT_ID)
    query = f"""
        SELECT submission_id, profile_type, raw_text
        FROM `{PROJECT_ID}.{BRONZE_DATASET}.raw_cv_texts`
    """
    rows = client.query(query).result()
    return [dict(row) for row in rows]


def get_processed_submission_ids(table, id_col="submission_id"):
    """
    Returns the set of submission_ids already present in `table`.

    Used for tables with no content_hash column (raw_work_experience,
    raw_skills). Change-detection already happened in extract_raw_text:
    a changed CV has its rows deleted from every bronze table via
    delete_cv_data before extract_entities runs, so "submission_id is
    already present" is sufficient to mean "already processed and unchanged".
    """
    client = bigquery.Client(project=PROJECT_ID)
    query = f"""
        SELECT DISTINCT {id_col}
        FROM `{PROJECT_ID}.{BRONZE_DATASET}.{table}`
    """
    try:
        rows = client.query(query).result()
        return {row[id_col] for row in rows}
    except NotFound:
        return set()

