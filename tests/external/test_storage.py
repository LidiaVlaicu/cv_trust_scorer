"""
Tests for the Companies House store.

The cache is what keeps the pipeline off the live API, so its three answers
matter: never searched, searched and found nothing, searched and found
something. A NOT_FOUND sentinel is how the middle one is recorded.
"""

from datetime import datetime, timezone

import pytest
from google.api_core.exceptions import NotFound

from external.companies_house.models import (
    CompanySearchResult,
    CompanyVerificationResult,
)
from external.companies_house.storage import CompanyHouseStorage

VERIFIED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def row(**overrides) -> dict:
    return {
        "company_number": "01234567",
        "company_name": "ACME LTD",
        "company_status": "active",
        "company_type": "ltd",
        "address_snippet": "1 High St",
        **overrides,
    }


class FakeJob:
    def __init__(self, rows=(), raises=None):
        self._rows = rows
        self._raises = raises

    def result(self):
        if self._raises:
            raise self._raises
        return self._rows


class RecordingClient:
    project = "a-project"

    def __init__(self, rows=(), raises=None, insert_errors=None):
        self.queries = []
        self.inserted = []
        self.created = []
        self._rows = rows
        self._raises = raises
        self._insert_errors = insert_errors or []

    def query(self, query, job_config=None):
        self.queries.append((query, job_config))
        return FakeJob(self._rows, self._raises)

    def insert_rows_json(self, table, rows):
        self.inserted.append((table, rows))
        return self._insert_errors

    def create_table(self, table, exists_ok=False):
        self.created.append(table)


@pytest.fixture(autouse=True)
def datasets(monkeypatch):
    monkeypatch.setenv("BQ_DATASET_BRONZE", "bronze")
    monkeypatch.setenv("BQ_DATASET_SILVER", "silver")
    monkeypatch.setenv("BQ_DATASET_GOLD", "gold")


def store(**kwargs) -> tuple[CompanyHouseStorage, RecordingClient]:
    schema = kwargs.pop("verification_schema", None)
    client = RecordingClient(**kwargs)
    return CompanyHouseStorage(client=client, verification_schema=schema), client


# ── addressing ────────────────────────────────────────────────────────────
def test_each_table_is_addressed_in_the_layer_it_belongs_to():
    storage, _ = store()

    assert storage.work_experience_table_id.endswith("silver.silver_work_experience")
    assert storage.search_table_id.endswith("bronze.companies_house_search_results")
    assert storage.verification_table_id.endswith("gold.signal_company_verification")


def test_the_employers_to_verify_come_back_as_plain_dicts():
    storage, _ = store(rows=[{"experience_id": "e1", "company_name": "ACME"}])

    assert storage.read_work_experience_companies() == [
        {"experience_id": "e1", "company_name": "ACME"}
    ]


# ── the cache ─────────────────────────────────────────────────────────────
def test_a_name_never_searched_is_a_miss():
    """None, not [] - the difference between unknown and known-absent."""
    storage, _ = store(rows=[])

    assert storage.get_cached_search("acme ltd") is None


def test_a_cached_not_found_is_an_empty_result_rather_than_a_miss():
    storage, _ = store(rows=[row(company_status="NOT_FOUND", company_number=None)])

    assert storage.get_cached_search("nonesuch ltd") == []


def test_a_cache_hit_comes_back_as_search_results():
    storage, _ = store(rows=[row()])

    (cached,) = storage.get_cached_search("acme ltd")
    assert cached.company_number == "01234567"
    assert cached.title == "ACME LTD"


def test_the_query_name_is_bound_as_a_parameter():
    storage, client = store(rows=[])

    storage.get_cached_search("o'brien ltd")

    query, job_config = client.queries[0]
    assert "o'brien" not in query
    assert job_config.query_parameters[0].value == "o'brien ltd"


# ── writing the cache ─────────────────────────────────────────────────────
def test_a_search_with_no_results_is_cached_as_not_found():
    """Otherwise a fake company is re-queried against the live API forever."""
    storage, client = store()

    storage.insert_search_results("Nonesuch Ltd", [])

    _, rows = client.inserted[0]
    assert len(rows) == 1
    assert rows[0]["company_status"] == "NOT_FOUND"
    assert rows[0]["company_number"] is None


def test_results_are_cached_under_the_normalized_name():
    storage, client = store()

    storage.insert_search_results("ACME Limited.", [])

    _, rows = client.inserted[0]
    assert rows[0]["company_query"] == "ACME Limited."
    assert rows[0]["company_query_normalized"] != "ACME Limited."


def test_every_result_of_a_search_is_cached():
    storage, client = store()
    found = [
        CompanySearchResult(company_number="1", title="A LTD"),
        CompanySearchResult(company_number="2", title="B LTD"),
    ]

    storage.insert_search_results("a ltd", found)

    _, rows = client.inserted[0]
    assert [r["company_number"] for r in rows] == ["1", "2"]


# ── the signal table ──────────────────────────────────────────────────────
def verification(**overrides) -> CompanyVerificationResult:
    return CompanyVerificationResult(
        submission_id="cv_1",
        experience_id="cv_1_1",
        company_name_cv="ACME LTD",
        matched_company_number="01234567",
        matched_company_name="ACME LTD",
        status="confirmed",
        verified_at=VERIFIED_AT,
        **overrides,
    )


def test_nothing_to_verify_writes_nothing():
    storage, client = store()

    storage.insert_verification_results([])

    assert client.inserted == []


def test_the_signal_table_is_created_when_a_schema_is_supplied():
    """The gold asset owns the schema; the table is appended to, not replaced."""
    storage, client = store(verification_schema=[])

    storage.insert_verification_results([verification()])

    assert client.created


def test_verification_rows_carry_an_iso_timestamp():
    storage, client = store()

    storage.insert_verification_results([verification()])

    _, rows = client.inserted[0]
    assert rows[0]["verified_at"] == VERIFIED_AT.isoformat()
    assert rows[0]["status"] == "confirmed"


def test_an_insert_that_reports_errors_raises():
    storage, _ = store(insert_errors=[{"index": 0}])

    with pytest.raises(RuntimeError):
        storage.insert_verification_results([verification()])


# ── resuming ──────────────────────────────────────────────────────────────
def test_already_verified_ids_are_returned_as_a_set():
    storage, _ = store(rows=[{"experience_id": "e1"}, {"experience_id": "e2"}])

    assert storage.get_verified_experience_ids() == {"e1", "e2"}


def test_a_signal_table_that_does_not_exist_yet_means_nothing_is_verified():
    storage, _ = store(raises=NotFound("no such table"))

    assert storage.get_verified_experience_ids() == set()


def test_any_other_failure_surfaces_rather_than_meaning_nothing_is_verified():
    """An empty set means "verify everything again" into an append-only table."""
    storage, _ = store(raises=ValueError("connection reset"))

    with pytest.raises(ValueError):
        storage.get_verified_experience_ids()


def test_a_failed_cache_write_raises():
    """A silently dropped cache row means paying for that search again."""
    storage, _ = store(insert_errors=[{"index": 0}])

    with pytest.raises(RuntimeError):
        storage.insert_search_results("ACME Ltd", [])
