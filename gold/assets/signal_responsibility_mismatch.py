"""
silver.silver_work_experience -> gold.signal_responsibility_mismatch

The I/O shell for the responsibility signal: the BigQuery adapter, the
injected run function and the Dagster asset. Every rule, threshold and
extraction pattern lives in gold/rules/responsibility_mismatch.py.
"""

from collections import Counter
from datetime import datetime, timezone
from typing import Callable, Protocol

from dagster import asset, get_dagster_logger
from google.cloud import bigquery

from shared import bigquery_client, dataset_name, replace_table, table_id
from gold.rules.responsibility_mismatch import build_signal_rows

SIGNAL_TABLE = "signal_responsibility_mismatch"
SIGNAL_SCHEMA = [
    bigquery.SchemaField("submission_id", "STRING", mode="REQUIRED"),
    # our confidence in the candidate's stated responsibilities
    bigquery.SchemaField("confidence", "STRING", mode="REQUIRED"),
    bigquery.SchemaField(
        "findings",
        "RECORD",
        mode="REPEATED",
        fields=[
            bigquery.SchemaField("name", "STRING", mode="REQUIRED"),
            # the role whose description carries the claim, so a reviewer can
            # find the sentence; the finding is not checkable without it
            bigquery.SchemaField("experience_id", "STRING", mode="REQUIRED"),
            # the seniority level contradicted - half of the contradiction
            bigquery.SchemaField("level", "STRING", mode="REQUIRED"),
            # size of the claim. People for the team findings, millions of
            # currency for the budget finding; which it is follows from the
            # name, as `months` does in the timeline signal.
            bigquery.SchemaField("claimed", "FLOAT64", mode="REQUIRED"),
            bigquery.SchemaField("evidence", "STRING", mode="REQUIRED"),
        ],
    ),
    bigquery.SchemaField("evaluated_at", "TIMESTAMP", mode="REQUIRED"),
]


# ── I/O boundary ──────────────────────────────────────────────────────────
class ResponsibilityWarehouse(Protocol):
    """Everything the responsibility signal needs from the warehouse."""

    def read_work_experience(self) -> list[dict]:
        """`silver_work_experience` rows."""

    def replace_signal(self, rows: list[dict]) -> None:
        """Replaces `signal_responsibility_mismatch` with `rows`."""


class BigQueryResponsibilityWarehouse:
    """ResponsibilityWarehouse backed by BigQuery."""

    def __init__(
        self,
        client: bigquery.Client | None = None,
        silver_dataset: str | None = None,
        gold_dataset: str | None = None,
    ) -> None:
        self._client = bigquery_client(client)
        self._silver = dataset_name("silver", silver_dataset)
        self._gold = dataset_name("gold", gold_dataset)

    def read_work_experience(self) -> list[dict]:
        query = f"""
            SELECT submission_id, experience_id, job_title, seniority_level,
                   description
            FROM `{self._client.project}.{self._silver}.silver_work_experience`
        """
        return [dict(row) for row in self._client.query(query).result()]

    def replace_signal(self, rows: list[dict]) -> None:
        """Full refresh: the signal is a pure function of silver."""
        replace_table(
            self._client,
            table_id(self._client, self._gold, SIGNAL_TABLE),
            rows,
            SIGNAL_SCHEMA,
        )


# ── Orchestration (dependencies injected) ─────────────────────────────────
def run_signal_responsibility_mismatch(
    warehouse: ResponsibilityWarehouse,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    report: Callable[[str], None] = lambda message: None,
) -> dict:
    """
    Reads silver, compares every role's claims against its stated level, writes
    the gold signal and returns run metadata. The warehouse and clock are
    injected so this runs with no BigQuery and no Dagster.
    """
    evaluated_at = now()

    work_experience = warehouse.read_work_experience()
    report(f"Read {len(work_experience)} work experience rows")

    signal_rows = build_signal_rows(work_experience, evaluated_at=evaluated_at)
    warehouse.replace_signal(signal_rows)
    report(f"Wrote {len(signal_rows)} candidate rows into {SIGNAL_TABLE}")

    confidences = Counter(row["confidence"] for row in signal_rows)
    names = Counter(
        finding["name"] for row in signal_rows for finding in row["findings"]
    )
    report(f"Confidence: {dict(confidences)}")
    report(f"Findings: {dict(names) or 'none'}")

    return {
        "candidates": len(signal_rows),
        "confidence": dict(confidences),
        "findings": dict(names),
    }


# ── ASSET: signal_responsibility_mismatch ─────────────────────────────────
@asset(deps=["silver_work_experience"])
def signal_responsibility_mismatch():
    """
    Trust signal: do the responsibilities claimed contradict the job title?

    Compares what each role description claims authority over - a team, direct
    reports, a budget - against the scope a published engineering ladder
    assigns to the stated seniority level. A Junior who directed a team of 28
    is claiming an E5 responsibility under an E2 title.

    Reports findings rather than a score, each naming the role it came from so
    the claim can be read back, and rolls them up into one confidence value per
    candidate.

    Writes one row per candidate to the gold dataset.
    """
    return run_signal_responsibility_mismatch(
        BigQueryResponsibilityWarehouse(),
        report=get_dagster_logger().info,
    )
