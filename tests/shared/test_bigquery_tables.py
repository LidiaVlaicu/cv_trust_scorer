"""
Tests for table addressing and the full-refresh write.

`replace_table` truncating rather than appending is the part worth pinning:
silver and gold are recomputed from the layer beneath them, so an append
would double the rows on every re-run.
"""

from shared.bigquery_tables import ensure_table, replace_table, table_id


class FakeLoadJob:
    def result(self):
        return None


class FakeClient:
    """Records what an adapter asked BigQuery to do."""

    project = "a-project"

    def __init__(self):
        self.created = []
        self.loads = []

    def create_table(self, table, exists_ok=False):
        self.created.append((table, exists_ok))

    def load_table_from_json(self, rows, table, job_config=None):
        self.loads.append((rows, table, job_config))
        return FakeLoadJob()


def test_table_id_is_project_dataset_table():
    assert table_id(FakeClient(), "bronze", "raw_cv_texts") == (
        "a-project.bronze.raw_cv_texts"
    )


def test_table_id_uses_the_project_of_the_client_it_is_given():
    client = FakeClient()
    client.project = "another-project"

    assert table_id(client, "gold", "signals").startswith("another-project.")


def test_ensure_table_tolerates_a_table_that_already_exists():
    client = FakeClient()

    ensure_table(client, "a-project.bronze.raw_cv_texts", schema=[])

    _, exists_ok = client.created[0]
    assert exists_ok is True


def test_replace_table_truncates_rather_than_appending():
    client = FakeClient()

    replace_table(client, "a-project.silver.candidates", [{"id": 1}], schema=[])

    _, _, job_config = client.loads[0]
    assert job_config.write_disposition == "WRITE_TRUNCATE"


def test_replace_table_sends_the_rows_it_was_given():
    client = FakeClient()
    rows = [{"id": 1}, {"id": 2}]

    replace_table(client, "a-project.silver.candidates", rows, schema=[])

    sent, table, _ = client.loads[0]
    assert sent == rows
    assert table == "a-project.silver.candidates"


def test_replace_table_waits_for_the_load_to_finish():
    """A load job that is never waited on can still be running on return."""
    finished = []

    class WatchedJob:
        def result(self):
            finished.append(True)

    client = FakeClient()
    client.load_table_from_json = lambda rows, table, job_config=None: WatchedJob()

    replace_table(client, "a-project.gold.signals", [], schema=[])

    assert finished == [True]
