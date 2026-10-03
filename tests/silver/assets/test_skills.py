"""
End-to-end test of the silver_skills pipeline against an in-memory fake
warehouse — no BigQuery, no Dagster, no credentials.

This is what injecting SkillsWarehouse into run_silver_skills() buys: the
orchestration itself (read taxonomy, read bronze, transform, write silver,
report unmatched) is verifiable in milliseconds.
"""

from datetime import datetime, timezone

from silver.assets.skills import (
    SILVER_SKILLS_SCHEMA,
    build_silver_skills_rows,
    run_silver_skills,
    summarize_unmatched,
)
from silver.rules.skills import build_skills_taxonomy

FIXED_TIME = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class FakeSkillsWarehouse:
    """In-memory SkillsWarehouse. Records what the pipeline would write."""

    def __init__(self, taxonomy_rows: list[dict], raw_skills: list[dict]) -> None:
        self._taxonomy_rows = taxonomy_rows
        self._raw_skills = raw_skills
        self.written: list[dict] | None = None
        self.write_count = 0

    def read_taxonomy(self) -> list[dict]:
        return self._taxonomy_rows

    def read_raw_skills(self) -> list[dict]:
        return self._raw_skills

    def replace_silver_skills(self, rows: list[dict]) -> None:
        self.written = rows
        self.write_count += 1


TAXONOMY_ROWS = [
    {"alias": "Power BI", "canonical_skill": "Power BI"},
    {"alias": "PowerBI", "canonical_skill": "Power BI"},
    {"alias": "Looker Studio", "canonical_skill": "Looker Studio"},
    {"alias": "Google Data Studio", "canonical_skill": "Looker Studio"},
]

RAW_SKILLS = [
    {"skill_id": "cv_1_a", "submission_id": "cv_1", "skill_name": "Power BI"},
    {"skill_id": "cv_1_b", "submission_id": "cv_1", "skill_name": "  powerbi "},
    {"skill_id": "cv_2_a", "submission_id": "cv_2", "skill_name": "Google Data Studio"},
    {"skill_id": "cv_2_b", "submission_id": "cv_2", "skill_name": "PowerBII"},
    {"skill_id": "cv_3_a", "submission_id": "cv_3", "skill_name": "PowerBII"},
]


def _run():
    warehouse = FakeSkillsWarehouse(TAXONOMY_ROWS, RAW_SKILLS)
    result = run_silver_skills(warehouse, now=lambda: FIXED_TIME)
    return warehouse, result


def test_writes_one_silver_row_per_bronze_row():
    warehouse, result = _run()

    assert warehouse.write_count == 1
    assert len(warehouse.written) == len(RAW_SKILLS)
    assert result["skills_count"] == len(RAW_SKILLS)


def test_normalizes_each_row_and_leaves_unknown_skills_null():
    warehouse, _ = _run()
    by_id = {row["skill_id"]: row for row in warehouse.written}

    assert by_id["cv_1_b"]["raw_skill"] == "  powerbi "
    assert by_id["cv_1_b"]["normalized_skill"] == "Power BI"

    assert by_id["cv_2_a"]["normalized_skill"] == "Looker Studio"
    assert by_id["cv_2_b"]["normalized_skill"] is None


def test_reports_counts_and_unmatched_skills():
    _, result = _run()

    assert result["matched_rows"] == 3
    assert result["unmatched_rows"] == 2
    assert result["distinct_normalized_skills"] == 2  # Power BI, Looker Studio
    assert result["top_unmatched"] == [("PowerBII", 2)]


def test_written_rows_match_the_bigquery_schema():
    """Guards against a column being added to the transform but not the schema."""
    warehouse, _ = _run()
    schema_fields = {field.name for field in SILVER_SKILLS_SCHEMA}

    for row in warehouse.written:
        assert set(row) == schema_fields


def test_every_row_carries_the_injected_timestamp():
    warehouse, _ = _run()
    assert {row["silver_processed_at"] for row in warehouse.written} == {
        FIXED_TIME.isoformat()
    }


def test_build_silver_skills_rows_is_pure():
    """Same inputs, same output - safe to rerun."""
    taxonomy = build_skills_taxonomy(TAXONOMY_ROWS)

    first = build_silver_skills_rows(RAW_SKILLS, taxonomy, FIXED_TIME)
    second = build_silver_skills_rows(RAW_SKILLS, taxonomy, FIXED_TIME)

    assert first == second


def test_summarize_unmatched_orders_by_frequency_and_respects_the_limit():
    rows = [
        {"raw_skill": "A", "normalized_skill": None},
        {"raw_skill": "B", "normalized_skill": None},
        {"raw_skill": "B", "normalized_skill": None},
        {"raw_skill": "C", "normalized_skill": "C"},
    ]

    assert summarize_unmatched(rows, 10) == [("B", 2), ("A", 1)]
    assert summarize_unmatched(rows, 1) == [("B", 2)]
    assert summarize_unmatched([], 10) == []


def test_summarize_unmatched_groups_spacing_and_case_variants_together():
    """The report should say 'Some Tool: 3', not list three near-identical rows."""
    rows = [
        {"raw_skill": "Some  Tool", "normalized_skill": None},
        {"raw_skill": " Some Tool ", "normalized_skill": None},
        {"raw_skill": "Some Tool", "normalized_skill": None},
    ]

    assert summarize_unmatched(rows, 10) == [("Some Tool", 3)]
