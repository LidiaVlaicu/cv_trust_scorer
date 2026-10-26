"""
What each layer does with nothing, and with rows missing a column.

Empty in, empty out: an empty source must produce an empty table rather
than a skipped write, because every silver and gold table is replaced
wholesale. Skipping the write would leave the previous run's rows behind
and quietly present them as current.

Missing columns: a row that lost a column is a contract break, and these
record that it surfaces as KeyError at the row that broke rather than as a
null travelling downstream.
"""

from datetime import datetime, timezone

import pytest

from gold.assets.signal_responsibility_mismatch import (
    run_signal_responsibility_mismatch,
)
from gold.assets.signal_timeline_consistency import run_signal_timeline_consistency
from silver.assets.silver_candidates import run_silver_candidates
from silver.assets.silver_skills import run_silver_skills
from silver.assets.silver_work_experience import run_silver_work_experience
from tests.rows import assert_no_rows, assert_rows_equal

FIXED_TIME = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class FakeWarehouse:
    """Answers every read with the rows it was given; records every write."""

    def __init__(self, **reads):
        self._reads = reads
        self.written: list[dict] | None = None
        self.write_count = 0

    def __getattr__(self, name):
        if name.startswith("read_"):
            return lambda: self._reads.get(name, [])
        if name.startswith("replace_"):
            return self._record
        raise AttributeError(name)

    def _record(self, rows: list[dict]) -> None:
        self.written = rows
        self.write_count += 1


EMPTY_CASES = [
    ("silver_candidates", run_silver_candidates),
    ("silver_work_experience", run_silver_work_experience),
    ("silver_skills", run_silver_skills),
    ("signal_timeline_consistency", run_signal_timeline_consistency),
    ("signal_responsibility_mismatch", run_signal_responsibility_mismatch),
]


@pytest.mark.parametrize("name,run", EMPTY_CASES, ids=[n for n, _ in EMPTY_CASES])
def test_an_empty_source_writes_an_empty_table(name, run):
    warehouse = FakeWarehouse()

    run(warehouse, now=lambda: FIXED_TIME)

    assert_no_rows(warehouse.written)


@pytest.mark.parametrize("name,run", EMPTY_CASES, ids=[n for n, _ in EMPTY_CASES])
def test_an_empty_source_still_writes_rather_than_skipping(name, run):
    """A skipped write would leave the previous run's rows looking current."""
    warehouse = FakeWarehouse()

    run(warehouse, now=lambda: FIXED_TIME)

    assert warehouse.write_count == 1


def test_a_row_missing_the_key_column_is_rejected():
    """submission_id is read directly: without it the row cannot be joined."""
    warehouse = FakeWarehouse(read_raw_candidates=[{"candidate_name": "Ada"}])

    with pytest.raises(KeyError, match="submission_id"):
        run_silver_candidates(warehouse, now=lambda: FIXED_TIME)


def test_gold_rejects_a_row_missing_the_key_column():
    warehouse = FakeWarehouse(read_work_experience=[{"experience_id": "cv_1_1"}])

    with pytest.raises(KeyError, match="submission_id"):
        run_signal_timeline_consistency(warehouse, now=lambda: FIXED_TIME)


def test_work_experience_rejects_a_row_missing_its_own_key():
    warehouse = FakeWarehouse(read_raw_work_experience=[{"submission_id": "cv_1"}])

    with pytest.raises(KeyError, match="experience_id"):
        run_silver_work_experience(warehouse, now=lambda: FIXED_TIME)


def test_a_row_missing_an_optional_column_is_written_with_a_blank():
    """
    Documents a tolerance worth knowing about: every column but the key is
    read with .get(), so an absent one becomes empty rather than failing.
    A column renamed upstream therefore reaches silver as blank data, not as
    an error - which is what test_layer_contracts.py exists to catch first.
    """
    warehouse = FakeWarehouse(
        read_raw_candidates=[{"submission_id": "cv_1", "candidate_name": "Ada"}]
    )

    run_silver_candidates(warehouse, now=lambda: FIXED_TIME)

    assert_rows_equal(
        warehouse.written,
        [
            {
                "submission_id": "cv_1",
                "candidate_name": "ADA",
                "email": "",
                "is_email_valid": False,
                "phone": None,
                "is_phone_valid": False,
                "linkedin": "",
                "github": "",
                "silver_processed_at": FIXED_TIME.isoformat(),
            }
        ],
    )
