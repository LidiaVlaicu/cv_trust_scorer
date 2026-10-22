"""
Tests for the write side of each BigQuery warehouse adapter.

The read side is covered by the column contract; this covers what each
adapter sends when it writes. Every silver and gold table is replaced
wholesale, so the assertion that matters is that a write is a full refresh
against the right table rather than an append.
"""

import pytest

from gold.assets.signal_responsibility_mismatch import BigQueryResponsibilityWarehouse
from gold.assets.signal_timeline_consistency import BigQueryTimelineWarehouse
from silver.assets.silver_candidates import BigQueryCandidatesWarehouse
from silver.assets.silver_skills import BigQuerySkillsWarehouse
from silver.assets.silver_work_experience import BigQueryWorkExperienceWarehouse

ROWS = [{"submission_id": "cv_1"}]


class FakeLoadJob:
    def result(self):
        return None


class RecordingClient:
    project = "a-project"

    def __init__(self):
        self.loads = []

    def load_table_from_json(self, rows, table, job_config=None):
        self.loads.append((rows, table, job_config))
        return FakeLoadJob()


WRITERS = [
    (BigQueryCandidatesWarehouse, "replace_silver_candidates", "silver_candidates"),
    (BigQuerySkillsWarehouse, "replace_silver_skills", "silver_skills"),
    (
        BigQueryWorkExperienceWarehouse,
        "replace_silver_work_experience",
        "silver_work_experience",
    ),
    (BigQueryTimelineWarehouse, "replace_signal", "signal_timeline_consistency"),
    (
        BigQueryResponsibilityWarehouse,
        "replace_signal",
        "signal_responsibility_mismatch",
    ),
]

IDS = [table for _, _, table in WRITERS]


def write(warehouse_class, method, rows=ROWS):
    client = RecordingClient()
    getattr(warehouse_class(client=client), method)(rows)
    return client.loads[0]


@pytest.mark.parametrize("warehouse,method,table", WRITERS, ids=IDS)
def test_each_adapter_writes_to_its_own_table(warehouse, method, table):
    _, written_table, _ = write(warehouse, method)

    assert written_table.endswith(f".{table}")


@pytest.mark.parametrize("warehouse,method,table", WRITERS, ids=IDS)
def test_every_write_is_a_full_refresh(warehouse, method, table):
    """An append would double the rows on a re-run of a recomputed table."""
    _, _, job_config = write(warehouse, method)

    assert job_config.write_disposition == "WRITE_TRUNCATE"


@pytest.mark.parametrize("warehouse,method,table", WRITERS, ids=IDS)
def test_the_rows_given_are_the_rows_sent(warehouse, method, table):
    rows, _, _ = write(warehouse, method)

    assert rows == ROWS


@pytest.mark.parametrize("warehouse,method,table", WRITERS, ids=IDS)
def test_an_empty_result_still_replaces_the_table(warehouse, method, table):
    """Skipping the write would leave the previous run's rows looking current."""
    rows, _, job_config = write(warehouse, method, rows=[])

    assert rows == []
    assert job_config.write_disposition == "WRITE_TRUNCATE"
