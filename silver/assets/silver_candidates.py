"""
bronze.raw_candidates -> silver.silver_candidates

Structure: a pure core and a thin I/O shell.

    build_silver_candidates_rows()  pure - the transformation, no BigQuery
    CandidatesWarehouse             protocol - every read/write this needs
    BigQueryCandidatesWarehouse     the only code here that touches BigQuery
    run_silver_candidates()         orchestration, with dependencies injected
    silver_candidates               Dagster asset - wires the real ones

Because the warehouse is injected, the whole pipeline can be exercised in
tests against an in-memory fake.
"""

from datetime import datetime, timezone
from typing import Callable, Protocol

from dagster import asset, get_dagster_logger
from google.cloud import bigquery

from shared import bigquery_client, dataset_name, replace_table, table_id
from silver.rules.candidates import transform_candidate_row

SILVER_CANDIDATES_TABLE = "silver_candidates"
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


# ── Pure core ─────────────────────────────────────────────────────────────
def build_silver_candidates_rows(
    raw_candidates: list[dict],
    processed_at: datetime,
) -> list[dict]:
    """
    Transforms every bronze row into its silver row. Pure: same inputs always
    give the same output, and nothing here reads or writes BigQuery.
    """
    timestamp = processed_at.isoformat()
    return [
        {**transform_candidate_row(row), "silver_processed_at": timestamp}
        for row in raw_candidates
    ]


# ── I/O boundary ──────────────────────────────────────────────────────────
class CandidatesWarehouse(Protocol):
    """Everything the silver_candidates pipeline needs from the warehouse."""

    def read_raw_candidates(self) -> list[dict]:
        """`raw_candidates` rows: {submission_id, candidate_name, email,
        phone, linkedin, github}."""

    def replace_silver_candidates(self, rows: list[dict]) -> None:
        """Replaces `silver_candidates` with `rows`."""


class BigQueryCandidatesWarehouse:
    """CandidatesWarehouse backed by BigQuery."""

    def __init__(
        self,
        client: bigquery.Client | None = None,
        bronze_dataset: str | None = None,
        silver_dataset: str | None = None,
    ) -> None:
        self._client = bigquery_client(client)
        self._bronze = dataset_name("bronze", bronze_dataset)
        self._silver = dataset_name("silver", silver_dataset)

    def read_raw_candidates(self) -> list[dict]:
        query = f"""
            SELECT submission_id, candidate_name, email, phone, linkedin, github
            FROM `{table_id(self._client, self._bronze, 'raw_candidates')}`
        """
        return [dict(row) for row in self._client.query(query).result()]

    def replace_silver_candidates(self, rows: list[dict]) -> None:
        """
        Full refresh: bronze is the source of truth, so silver is rebuilt from
        it rather than appended to (no duplicate or stale rows on reruns).
        """
        replace_table(
            self._client,
            table_id(self._client, self._silver, SILVER_CANDIDATES_TABLE),
            rows,
            SILVER_CANDIDATES_SCHEMA,
        )


# ── Orchestration (dependencies injected) ─────────────────────────────────
def run_silver_candidates(
    warehouse: CandidatesWarehouse,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    report: Callable[[str], None] = lambda message: None,
) -> dict:
    """
    Reads bronze, transforms, writes silver, and returns run metadata. The
    warehouse, the clock and the reporter are injected so this is runnable
    with no BigQuery and no Dagster.
    """
    raw_candidates = warehouse.read_raw_candidates()
    report(f"Read {len(raw_candidates)} rows from raw_candidates")

    silver_rows = build_silver_candidates_rows(raw_candidates, now())
    warehouse.replace_silver_candidates(silver_rows)
    report(f"Loaded {len(silver_rows)} rows into {SILVER_CANDIDATES_TABLE}")

    invalid_emails = sum(1 for row in silver_rows if not row["is_email_valid"])
    invalid_phones = sum(1 for row in silver_rows if not row["is_phone_valid"])
    report(f"Invalid emails: {invalid_emails}, invalid phones: {invalid_phones}")

    return {
        "candidates_count": len(silver_rows),
        "invalid_emails": invalid_emails,
        "invalid_phones": invalid_phones,
    }


# ── ASSET: silver_candidates ──────────────────────────────────────────────
@asset(deps=["extract_entities"])
def silver_candidates():
    """
    Standardizes and validates bronze raw_candidates into silver_candidates.

    - candidate_name: uppercased, whitespace-collapsed
    - phone: normalized to E.164 (e.g. +442071838750), NULL if it can't be
    - email: kept as-is, with an is_email_valid flag (has "@", a domain,
      no spaces, and matches a standard email pattern)
    """
    return run_silver_candidates(
        BigQueryCandidatesWarehouse(),
        report=get_dagster_logger().info,
    )
