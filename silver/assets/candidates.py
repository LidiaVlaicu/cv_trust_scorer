import os
from datetime import datetime, timezone

from dagster import asset, get_dagster_logger
from google.cloud import bigquery

from warehouse import bigquery_client, replace_table, table_id

from silver.rules.candidates import transform_candidate_row

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
BRONZE_DATASET = os.getenv("BQ_DATASET_BRONZE")
SILVER_DATASET = os.getenv("BQ_DATASET_SILVER")

SILVER_CANDIDATES_SCHEMA = [
    bigquery.SchemaField("submission_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("candidate_name", "STRING"),
    bigquery.SchemaField("email", "STRING"),
    bigquery.SchemaField("is_email_valid", "BOOLEAN"),
    bigquery.SchemaField("phone", "STRING"),
    bigquery.SchemaField("is_phone_valid", "BOOLEAN"),
    bigquery.SchemaField("linkedin", "STRING"),
    bigquery.SchemaField("github", "STRING"),
    bigquery.SchemaField("silver_processed_at", "TIMESTAMP", mode="REQUIRED"),
]


def _get_raw_candidates() -> list[dict]:
    client = bigquery.Client(project=PROJECT_ID)
    query = f"""
        SELECT submission_id, candidate_name, email, phone, linkedin, github
        FROM `{PROJECT_ID}.{BRONZE_DATASET}.raw_candidates`
    """
    rows = client.query(query).result()
    return [dict(row) for row in rows]


def _load_silver_candidates(rows: list[dict]) -> None:
    """
    Full refresh of silver_candidates: bronze raw_candidates is the source
    of truth, so silver is rebuilt from it each run rather than
    incrementally appended (avoids duplicate/stale rows on reprocessing).
    """
    client = bigquery_client()
    replace_table(
        client,
        table_id(client, SILVER_DATASET, "silver_candidates"),
        rows,
        SILVER_CANDIDATES_SCHEMA,
    )


# ── ASSET: silver_candidates ───────────────────────────────────────────────
@asset(deps=["extract_entities"])
def silver_candidates():
    """
    Standardizes and validates bronze raw_candidates into silver_candidates.

    - candidate_name: uppercased, whitespace-collapsed
    - phone: normalized to E.164 (e.g. +442071838750), NULL if it can't be
    - email: kept as-is, with an is_email_valid flag (has "@", a domain,
      no spaces, and matches a standard email pattern)
    """
    log = get_dagster_logger()

    raw_rows = _get_raw_candidates()
    log.info(f"Read {len(raw_rows)} rows from raw_candidates")

    processed_at = datetime.now(timezone.utc).isoformat()
    silver_rows = []
    for row in raw_rows:
        transformed = transform_candidate_row(row)
        transformed["silver_processed_at"] = processed_at
        silver_rows.append(transformed)

    _load_silver_candidates(silver_rows)
    log.info(f"Loaded {len(silver_rows)} rows into silver_candidates")

    invalid_emails = sum(1 for r in silver_rows if not r["is_email_valid"])
    invalid_phones = sum(1 for r in silver_rows if not r["is_phone_valid"])
    log.info(
        f"Invalid emails: {invalid_emails}, invalid phones: {invalid_phones}"
    )

    return {
        "candidates_count": len(silver_rows),
        "invalid_emails": invalid_emails,
        "invalid_phones": invalid_phones,
    }
