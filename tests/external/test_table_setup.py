"""
Tests for the Companies House cache table setup.

The cache holds paid-for API responses, so this script must never replace a
table that already exists. Its three paths are: create it, widen it with new
nullable columns, or leave it alone.
"""

import pytest
from google.cloud import bigquery

from external.companies_house import table_setup


class RecordingClient:
    project = "a-project"

    def __init__(self, existing_schema=None):
        self._existing_schema = existing_schema
        self.created = []
        self.updated = []

    def get_table(self, table_id):
        if self._existing_schema is None:
            raise Exception("404 Not found")
        return bigquery.Table(table_id, schema=self._existing_schema)

    def create_table(self, table):
        self.created.append(table)

    def update_table(self, table, fields):
        self.updated.append((table, fields))


@pytest.fixture
def client(monkeypatch):
    def install(existing_schema=None):
        recorder = RecordingClient(existing_schema)
        monkeypatch.setattr(
            table_setup.bigquery, "Client", lambda project=None: recorder
        )
        return recorder

    return install


def test_a_missing_table_is_created(client):
    recorder = client()

    table_setup.create_table()

    assert len(recorder.created) == 1
    assert recorder.updated == []


def test_the_created_table_carries_the_whole_schema(client):
    recorder = client()

    table_setup.create_table()

    names = {field.name for field in recorder.created[0].schema}
    assert {"company_query", "company_query_normalized", "retrieved_at"} <= names


def test_the_table_lands_in_the_bronze_dataset(client, monkeypatch):
    monkeypatch.setenv("BQ_DATASET_BRONZE", "bronze")
    recorder = client()

    table_setup.create_table()

    assert "bronze.companies_house_search_results" in str(recorder.created[0].reference)


def test_an_existing_table_is_never_recreated(client):
    """Recreating it would discard responses that were paid for."""
    recorder = client(existing_schema=[bigquery.SchemaField("company_query", "STRING")])

    table_setup.create_table()

    assert recorder.created == []


def test_columns_missing_from_an_existing_table_are_added(client):
    recorder = client(existing_schema=[bigquery.SchemaField("company_query", "STRING")])

    table_setup.create_table()

    table, fields = recorder.updated[0]
    assert fields == ["schema"]
    assert "retrieved_at" in {field.name for field in table.schema}


def test_an_up_to_date_table_is_left_alone(client):
    full_schema = [
        bigquery.SchemaField(name, "STRING")
        for name in (
            "company_query",
            "company_query_normalized",
            "company_number",
            "company_name",
            "company_status",
            "company_type",
            "address_snippet",
            "retrieved_at",
        )
    ]
    recorder = client(existing_schema=full_schema)

    table_setup.create_table()

    assert recorder.created == []
    assert recorder.updated == []
