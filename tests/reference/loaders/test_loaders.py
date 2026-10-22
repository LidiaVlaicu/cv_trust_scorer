"""
Tests for the three reference loaders.

Each one parses a reviewed CSV and replaces a silver dimension wholesale.
The write is intercepted, so what is checked is the rows that would be sent,
the table they go to, and that a replace is used rather than an append - an
incremental load would leave aliases from an older taxonomy behind.
"""

import pytest

from reference.loaders import (
    load_dim_job_titles,
    load_dim_location_aliases,
    load_dim_skills,
)
from tests.rows import assert_rows_equal

CSVS = {
    "skills": "canonical_skill,aliases\nPython,python|py\n",
    "job_titles": "job_title,seniority_level\nStaff Engineer,Staff\n",
    "locations": "location_token,country\nDublin,Ireland\n",
}


class Recorder:
    def __init__(self):
        self.writes = []

    def replace_table(self, client, table, rows, schema):
        self.writes.append({"table": table, "rows": rows, "schema": schema})


@pytest.fixture
def load(monkeypatch, tmp_path):
    """Runs a loader against a CSV on disk, capturing the write."""

    def go(module, loader_name, csv_text):
        recorder = Recorder()
        monkeypatch.setattr(module, "bigquery_client", lambda: object())
        monkeypatch.setattr(module, "table_id", lambda c, d, t: f"p.{d}.{t}")
        monkeypatch.setattr(module, "dataset_name", lambda layer: layer)
        monkeypatch.setattr(module, "replace_table", recorder.replace_table)
        path = tmp_path / "reviewed.csv"
        path.write_text(csv_text, encoding="utf-8")
        count = getattr(module, loader_name)(path)
        return recorder.writes[0], count

    return go


CASES = [
    ("skills", load_dim_skills, "load_dim_skills", "p.silver.dim_skills"),
    (
        "job_titles",
        load_dim_job_titles,
        "load_dim_job_titles",
        "p.silver.dim_job_titles",
    ),
    (
        "locations",
        load_dim_location_aliases,
        "load_dim_location_aliases",
        "p.silver.dim_location_aliases",
    ),
]


@pytest.mark.parametrize(
    "csv_key,module,loader,table", CASES, ids=[c[0] for c in CASES]
)
def test_each_dimension_is_written_to_its_table_in_silver(
    load, csv_key, module, loader, table
):
    write, _ = load(module, loader, CSVS[csv_key])

    assert write["table"] == table


@pytest.mark.parametrize(
    "csv_key,module,loader,table", CASES, ids=[c[0] for c in CASES]
)
def test_each_loader_returns_the_number_of_rows_it_wrote(
    load, csv_key, module, loader, table
):
    write, count = load(module, loader, CSVS[csv_key])

    assert count == len(write["rows"])
    assert count > 0


@pytest.mark.parametrize(
    "csv_key,module,loader,table", CASES, ids=[c[0] for c in CASES]
)
def test_every_row_matches_the_declared_schema(load, csv_key, module, loader, table):
    write, _ = load(module, loader, CSVS[csv_key])

    declared = {field.name for field in write["schema"]}
    for row in write["rows"]:
        assert set(row) == declared


def test_an_alias_row_is_written_for_every_alias_in_the_taxonomy(load):
    write, _ = load(load_dim_skills, "load_dim_skills", CSVS["skills"])

    assert_rows_equal(
        write["rows"],
        [
            {"alias": "python", "canonical_skill": "Python"},
            {"alias": "py", "canonical_skill": "Python"},
        ],
    )


def test_a_job_title_keeps_its_reviewed_seniority(load):
    write, _ = load(load_dim_job_titles, "load_dim_job_titles", CSVS["job_titles"])

    assert_rows_equal(
        write["rows"], [{"job_title": "Staff Engineer", "seniority_level": "Staff"}]
    )


def test_a_location_keeps_its_reviewed_country(load):
    write, _ = load(
        load_dim_location_aliases, "load_dim_location_aliases", CSVS["locations"]
    )

    assert_rows_equal(
        write["rows"], [{"location_token": "Dublin", "country": "Ireland"}]
    )
