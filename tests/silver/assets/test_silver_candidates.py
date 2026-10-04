"""
End-to-end test of the silver_candidates pipeline against an in-memory fake
warehouse — no BigQuery, no Dagster, no credentials.
"""

from datetime import datetime, timezone

from silver.assets.silver_candidates import (
    SILVER_CANDIDATES_SCHEMA,
    build_silver_candidates_rows,
    run_silver_candidates,
)

FIXED_TIME = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class FakeCandidatesWarehouse:
    """In-memory CandidatesWarehouse. Records what the pipeline would write."""

    def __init__(self, raw_candidates: list[dict]) -> None:
        self._raw_candidates = raw_candidates
        self.written: list[dict] | None = None
        self.write_count = 0

    def read_raw_candidates(self) -> list[dict]:
        return self._raw_candidates

    def replace_silver_candidates(self, rows: list[dict]) -> None:
        self.written = rows
        self.write_count += 1


RAW_CANDIDATES = [
    {
        "submission_id": "cv_1",
        "candidate_name": "  ada   lovelace ",
        "email": "ada@example.com",
        "phone": "+44 20 7183 8750",
        "linkedin": " https://linkedin.com/in/ada ",
        "github": "",
    },
    {
        "submission_id": "cv_2",
        "candidate_name": "Grace Hopper",
        "email": "not an email",
        "phone": "12345",
        "linkedin": "",
        "github": "https://github.com/grace",
    },
    {
        "submission_id": "cv_3",
        "candidate_name": None,
        "email": None,
        "phone": None,
        "linkedin": None,
        "github": None,
    },
]


def _run():
    warehouse = FakeCandidatesWarehouse(RAW_CANDIDATES)
    result = run_silver_candidates(warehouse, now=lambda: FIXED_TIME)
    return warehouse, result


def test_writes_one_silver_row_per_bronze_row():
    warehouse, result = _run()

    assert warehouse.write_count == 1
    assert len(warehouse.written) == len(RAW_CANDIDATES)
    assert result["candidates_count"] == len(RAW_CANDIDATES)


def test_standardizes_name_and_phone():
    warehouse, _ = _run()
    by_id = {row["submission_id"]: row for row in warehouse.written}

    assert by_id["cv_1"]["candidate_name"] == "ADA LOVELACE"
    assert by_id["cv_1"]["phone"] == "+442071838750"
    assert by_id["cv_1"]["is_phone_valid"] is True


def test_flags_bad_email_and_phone_without_dropping_the_row():
    warehouse, result = _run()
    by_id = {row["submission_id"]: row for row in warehouse.written}

    assert by_id["cv_2"]["is_email_valid"] is False
    assert by_id["cv_2"]["phone"] is None
    assert by_id["cv_2"]["is_phone_valid"] is False

    assert result["invalid_emails"] == 2  # cv_2 and the empty cv_3
    assert result["invalid_phones"] == 2


def test_missing_fields_become_empty_strings():
    warehouse, _ = _run()
    by_id = {row["submission_id"]: row for row in warehouse.written}

    assert by_id["cv_3"]["candidate_name"] == ""
    assert by_id["cv_3"]["email"] == ""
    assert by_id["cv_3"]["linkedin"] == ""
    assert by_id["cv_3"]["github"] == ""


def test_written_rows_match_the_bigquery_schema():
    """Guards against a column being added to the transform but not the schema."""
    warehouse, _ = _run()
    schema_fields = {field.name for field in SILVER_CANDIDATES_SCHEMA}

    for row in warehouse.written:
        assert set(row) == schema_fields


def test_every_row_carries_the_injected_timestamp():
    warehouse, _ = _run()
    assert {row["silver_processed_at"] for row in warehouse.written} == {
        FIXED_TIME.isoformat()
    }


def test_build_silver_candidates_rows_is_pure():
    """Same inputs, same output - safe to rerun."""
    first = build_silver_candidates_rows(RAW_CANDIDATES, FIXED_TIME)
    second = build_silver_candidates_rows(RAW_CANDIDATES, FIXED_TIME)

    assert first == second
