"""
Tests for the bronze warehouse adapter.

A recording client stands in for BigQuery, so what is checked is the
behaviour around the call: a first run against a table that does not exist
yet, an insert that reports errors, and the parameter binding that keeps a
submission id out of the SQL text.
"""

import pytest
from google.api_core.exceptions import NotFound

from bronze.io import bigquery_persistence as adapter


class FakeJob:
    def __init__(self, rows=(), raises=None):
        self._rows = rows
        self._raises = raises

    def result(self):
        if self._raises:
            raise self._raises
        return self._rows


class RecordingClient:
    """Records queries and inserts; answers with whatever it was handed."""

    def __init__(self, rows=(), raises=None, insert_errors=None):
        self.queries: list[tuple[str, object]] = []
        self.inserted: list[tuple[str, list]] = []
        self._rows = rows
        self._raises = raises
        self._insert_errors = insert_errors or []

    def query(self, query, job_config=None):
        self.queries.append((query, job_config))
        return FakeJob(self._rows, self._raises)

    def insert_rows_json(self, table, rows):
        self.inserted.append((table, rows))
        return self._insert_errors


@pytest.fixture
def client(monkeypatch):
    """Installs a recording client in place of bigquery.Client."""

    def install(**kwargs):
        recorder = RecordingClient(**kwargs)
        monkeypatch.setattr(adapter.bigquery, "Client", lambda project=None: recorder)
        return recorder

    return install


# ── inserts ───────────────────────────────────────────────────────────────
def test_rows_are_handed_to_the_table_they_belong_to(client):
    recorder = client()

    adapter.insert_rows_to_bigquery("p.d.raw_skills", [{"skill_id": "s1"}])

    assert recorder.inserted == [("p.d.raw_skills", [{"skill_id": "s1"}])]


def test_insert_errors_are_raised_rather_than_returned(client):
    """BigQuery reports per-row failures in its return value, not by raising."""
    client(insert_errors=[{"index": 0, "errors": ["bad row"]}])

    with pytest.raises(Exception, match="BigQuery insert errors"):
        adapter.insert_rows_to_bigquery("p.d.raw_skills", [{"skill_id": "s1"}])


def test_a_clean_insert_raises_nothing(client):
    client(insert_errors=[])

    adapter.insert_rows_to_bigquery("p.d.raw_skills", [{"skill_id": "s1"}])


# ── deletes ───────────────────────────────────────────────────────────────
def test_deleting_a_cv_clears_every_bronze_table(client):
    recorder = client()

    adapter.delete_cv_data("cv_1")

    tables = {"raw_cv_texts", "raw_candidates", "raw_work_experience", "raw_skills"}
    assert {t for t in tables if any(t in q for q, _ in recorder.queries)} == tables


def test_the_submission_id_is_bound_as_a_parameter_not_inlined(client):
    """A name with an apostrophe would otherwise break or inject SQL."""
    recorder = client()

    adapter.delete_cv_data("o'brien_cv")

    query, job_config = recorder.queries[0]
    assert "o'brien_cv" not in query
    assert job_config.query_parameters[0].value == "o'brien_cv"


# ── reads ─────────────────────────────────────────────────────────────────
def test_processed_versions_are_returned_as_id_to_hash(client):
    client(rows=[{"submission_id": "cv_1", "content_hash": "abc"}])

    assert adapter.get_processed_versions("raw_cv_texts") == {"cv_1": "abc"}


def test_a_table_that_does_not_exist_yet_reads_as_no_versions(client):
    """First run: the table is created by the write that follows."""
    client(raises=NotFound("no such table"))

    assert adapter.get_processed_versions("raw_cv_texts") == {}


def test_processed_ids_are_returned_as_a_set(client):
    client(rows=[{"submission_id": "cv_1"}, {"submission_id": "cv_2"}])

    assert adapter.get_processed_submission_ids("raw_skills") == {"cv_1", "cv_2"}


def test_a_table_that_does_not_exist_yet_reads_as_no_ids(client):
    client(raises=NotFound("no such table"))

    assert adapter.get_processed_submission_ids("raw_skills") == set()


def test_cv_texts_come_back_as_plain_dicts(client):
    client(rows=[{"submission_id": "cv_1", "profile_type": "tech", "raw_text": "x"}])

    assert adapter.get_all_cv_texts() == [
        {"submission_id": "cv_1", "profile_type": "tech", "raw_text": "x"}
    ]


def test_an_empty_table_reads_as_no_cv_texts(client):
    client(rows=[])

    assert adapter.get_all_cv_texts() == []


def test_ensuring_a_table_passes_the_schema_through(monkeypatch):
    """The only call that delegates to the shared helper rather than the client."""
    seen = []
    monkeypatch.setattr(adapter.bigquery, "Client", lambda project=None: "client")
    monkeypatch.setattr(
        adapter,
        "shared_ensure_table",
        lambda client, table, schema: seen.append((client, table, schema)),
    )

    adapter.ensure_table("p.d.raw_cv_texts", ["a schema"])

    assert seen == [("client", "p.d.raw_cv_texts", ["a schema"])]
