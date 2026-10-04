"""
bronze.raw_skills -> silver.silver_skills

Structure: a pure core and a thin I/O shell.

    build_silver_skills_rows()  pure - the actual transformation, no BigQuery
    SkillsWarehouse             protocol - every read/write this needs
    BigQuerySkillsWarehouse     the only code here that touches BigQuery
    run_silver_skills()         orchestration, with its dependencies injected
    silver_skills               Dagster asset - wires the real implementations

Because the warehouse is injected, the whole pipeline can be exercised in
tests against an in-memory fake; see tests/silver/assets/test_silver_skills.py.
"""

from collections import Counter
from datetime import datetime, timezone
from typing import Callable, Protocol

from dagster import asset, get_dagster_logger
from google.cloud import bigquery

from shared import bigquery_client, dataset_name, replace_table, table_id
from silver.rules.skills import (
    SkillsTaxonomy,
    build_skills_taxonomy,
    clean_skill,
    transform_skill_row,
)

SILVER_SKILLS_TABLE = "silver_skills"
SILVER_SKILLS_SCHEMA = [
    bigquery.SchemaField("skill_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("submission_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("raw_skill", "STRING"),
    bigquery.SchemaField("normalized_skill", "STRING"),
    bigquery.SchemaField("silver_processed_at", "TIMESTAMP", mode="REQUIRED"),
]

UNMATCHED_SAMPLE_SIZE = 10


# ── Pure core ─────────────────────────────────────────────────────────────
def build_silver_skills_rows(
    raw_skills: list[dict],
    taxonomy: SkillsTaxonomy,
    processed_at: datetime,
) -> list[dict]:
    """
    Transforms every bronze row into its silver row. Pure: same inputs always
    give the same output, and nothing here reads or writes BigQuery.
    """
    timestamp = processed_at.isoformat()
    return [
        {**transform_skill_row(row, taxonomy), "silver_processed_at": timestamp}
        for row in raw_skills
    ]


def summarize_unmatched(silver_rows: list[dict], sample_size: int) -> list[tuple[str, int]]:
    """
    The most frequent skills that did not match the taxonomy, worst first.

    Counted on the cleaned form so that casing and spacing variants of the
    same unknown skill are reported once. This is the maintenance signal:
    whatever it returns is what should be reviewed and added to
    skills_taxonomy_review.csv.
    """
    unmatched = Counter(
        clean_skill(row["raw_skill"])
        for row in silver_rows
        if row["normalized_skill"] is None
    )
    return unmatched.most_common(sample_size)


# ── I/O boundary ──────────────────────────────────────────────────────────
class SkillsWarehouse(Protocol):
    """Everything the silver_skills pipeline needs from the warehouse."""

    def read_taxonomy(self) -> list[dict]:
        """`dim_skills` rows: {alias, canonical_skill}."""

    def read_raw_skills(self) -> list[dict]:
        """`raw_skills` rows: {skill_id, submission_id, skill_name}."""

    def replace_silver_skills(self, rows: list[dict]) -> None:
        """Replaces `silver_skills` with `rows`."""


class BigQuerySkillsWarehouse:
    """SkillsWarehouse backed by BigQuery."""

    def __init__(
        self,
        client: bigquery.Client | None = None,
        bronze_dataset: str | None = None,
        silver_dataset: str | None = None,
    ) -> None:
        self._client = bigquery_client(client)
        self._bronze = dataset_name("bronze", bronze_dataset)
        self._silver = dataset_name("silver", silver_dataset)

    def read_taxonomy(self) -> list[dict]:
        query = f"SELECT alias, canonical_skill FROM `{table_id(self._client, self._silver, 'dim_skills')}`"
        return [dict(row) for row in self._client.query(query).result()]

    def read_raw_skills(self) -> list[dict]:
        query = f"""
            SELECT skill_id, submission_id, skill_name
            FROM `{table_id(self._client, self._bronze, 'raw_skills')}`
        """
        return [dict(row) for row in self._client.query(query).result()]

    def replace_silver_skills(self, rows: list[dict]) -> None:
        """
        Full refresh: bronze is the source of truth, so silver is rebuilt from
        it rather than appended to (no duplicate or stale rows on reruns).
        """
        replace_table(
            self._client,
            table_id(self._client, self._silver, SILVER_SKILLS_TABLE),
            rows,
            SILVER_SKILLS_SCHEMA,
        )


# ── Orchestration (dependencies injected) ─────────────────────────────────
def run_silver_skills(
    warehouse: SkillsWarehouse,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    report: Callable[[str], None] = lambda message: None,
) -> dict:
    """
    Reads bronze and the taxonomy, transforms, writes silver, and returns run
    metadata. `warehouse`, the clock and the reporter are injected so this is
    runnable with no BigQuery and no Dagster.
    """
    taxonomy = build_skills_taxonomy(warehouse.read_taxonomy())
    report(f"Taxonomy: {taxonomy.alias_count} aliases -> {len(taxonomy.canonical_skills)} canonical skills")

    raw_skills = warehouse.read_raw_skills()
    report(f"Read {len(raw_skills)} rows from raw_skills")

    silver_rows = build_silver_skills_rows(raw_skills, taxonomy, now())
    warehouse.replace_silver_skills(silver_rows)
    report(f"Loaded {len(silver_rows)} rows into {SILVER_SKILLS_TABLE}")

    unmatched = summarize_unmatched(silver_rows, UNMATCHED_SAMPLE_SIZE)
    unmatched_rows = sum(1 for row in silver_rows if row["normalized_skill"] is None)
    if unmatched:
        report(
            f"{unmatched_rows} rows did not match the taxonomy. "
            f"Add these to skills_taxonomy_review.csv: {unmatched}"
        )

    return {
        "skills_count": len(silver_rows),
        "matched_rows": len(silver_rows) - unmatched_rows,
        "unmatched_rows": unmatched_rows,
        "distinct_normalized_skills": len(
            {row["normalized_skill"] for row in silver_rows if row["normalized_skill"]}
        ),
        "top_unmatched": unmatched,
    }


# ── ASSET: silver_skills ──────────────────────────────────────────────────
@asset(deps=["extract_entities"])
def silver_skills():
    """
    Cleans, standardizes, normalizes and validates bronze raw_skills into
    silver_skills, using the `dim_skills` reference table as the controlled
    vocabulary.

    - raw_skill: untouched original, for traceability
    - normalized_skill: canonical skill from dim_skills, NULL when the skill
      is not in the taxonomy (the validation signal — the row is kept, not
      dropped, so it can be reviewed and added)

    Cleaning (Unicode/whitespace) and standardization (lowercasing for the
    lookup) happen inside the transform; they are not persisted as columns.
    """
    return run_silver_skills(
        BigQuerySkillsWarehouse(),
        report=get_dagster_logger().info,
    )
