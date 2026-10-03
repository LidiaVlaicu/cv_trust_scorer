"""
silver.silver_work_experience -> gold.signal_timeline_consistency

The I/O shell for the timeline signal: the BigQuery adapter, the injected
run function and the Dagster asset. Every rule and threshold lives in
gold/rules/timeline_consistency.py, which this module must not duplicate.
"""

from collections import Counter
from datetime import date, datetime, timezone
from typing import Callable, Protocol

from dagster import asset, get_dagster_logger
from google.cloud import bigquery

from warehouse import bigquery_client, dataset_name, replace_table, table_id
from gold.rules.timeline_consistency import build_signal_rows

SIGNAL_TABLE = "signal_timeline_consistency"
SIGNAL_SCHEMA = [
    bigquery.SchemaField("submission_id", "STRING", mode="REQUIRED"),
    # our confidence in the candidate's timeline, not in the finding
    bigquery.SchemaField("confidence", "STRING", mode="REQUIRED"),
    bigquery.SchemaField(
        "findings",
        "RECORD",
        mode="REPEATED",
        fields=[
            bigquery.SchemaField("name", "STRING", mode="REQUIRED"),
            # the measured size of the finding; which kind of months it counts
            # is clear from the name (overlap, gap, experience missing).
            # NULL where there is nothing to measure in months.
            bigquery.SchemaField("months", "INT64"),
            # how strong this piece of evidence is
            bigquery.SchemaField("evidence", "STRING", mode="REQUIRED"),
        ],
    ),
    bigquery.SchemaField("as_of_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("evaluated_at", "TIMESTAMP", mode="REQUIRED"),
]


# ── I/O boundary ──────────────────────────────────────────────────────────
class TimelineWarehouse(Protocol):
    """Everything the timeline signal needs from the warehouse."""

    def read_work_experience(self) -> list[dict]:
        """`silver_work_experience` rows."""

    def replace_signal(self, rows: list[dict]) -> None:
        """Replaces `signal_timeline_consistency` with `rows`."""


class BigQueryTimelineWarehouse:
    """TimelineWarehouse backed by BigQuery."""

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
                   start_date, end_date, is_current
            FROM `{self._client.project}.{self._silver}.silver_work_experience`
        """
        return [dict(row) for row in self._client.query(query).result()]

    def replace_signal(self, rows: list[dict]) -> None:
        """
        Full refresh: the signal is a pure function of silver, so it is
        recomputed rather than accumulated.
        """
        replace_table(
            self._client,
            table_id(self._client, self._gold, SIGNAL_TABLE),
            rows,
            SIGNAL_SCHEMA,
        )


# ── Orchestration (dependencies injected) ─────────────────────────────────
def run_signal_timeline_consistency(
    warehouse: TimelineWarehouse,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    as_of: date | None = None,
    report: Callable[[str], None] = lambda message: None,
) -> dict:
    """
    Reads silver, evaluates every candidate's timeline, writes the gold signal
    and returns run metadata. The warehouse, clock and as-of date are injected
    so this runs with no BigQuery and no Dagster.
    """
    evaluated_at = now()
    as_of_date = as_of or evaluated_at.date()

    work_experience = warehouse.read_work_experience()
    report(f"Read {len(work_experience)} work experience rows")

    signal_rows = build_signal_rows(
        work_experience, as_of=as_of_date, evaluated_at=evaluated_at
    )
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
        "as_of_date": as_of_date.isoformat(),
    }


# ── ASSET: signal_timeline_consistency ────────────────────────────────────
@asset(deps=["silver_work_experience"])
def signal_timeline_consistency():
    """
    Trust signal: is the candidate's employment timeline internally possible?

    Reports findings rather than a score. Each finding names what was detected,
    how large it is in months, and how strong that kind of evidence proved to
    be on the labelled CV set. Those roll up into one confidence value per
    candidate by a single stated rule: proven evidence means the timeline is
    not_confirmed, suggestive evidence alone means possible, nothing found
    means confirmed.

    Writes one row per candidate to the gold dataset.
    """
    return run_signal_timeline_consistency(
        BigQueryTimelineWarehouse(),
        report=get_dagster_logger().info,
    )
