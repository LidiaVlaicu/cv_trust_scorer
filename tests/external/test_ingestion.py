"""
Tests for the Companies House ingestion entry points.

Both are thin: one returns the search results, the other caches them. The
client and the store are replaced, so no request is made.
"""

import pytest

from external.companies_house import ingestion
from external.companies_house.models import CompanySearchResult

FOUND = [CompanySearchResult(company_number="01234567", title="ACME LTD")]


class FakeClient:
    def __init__(self, items=FOUND):
        self.searched = []
        self._items = items

    def search_company(self, name):
        self.searched.append(name)
        return type("R", (), {"items": self._items})()


class FakeStore:
    def __init__(self):
        self.cached = []

    def insert_search_results(self, name, results):
        self.cached.append((name, results))


@pytest.fixture
def wiring(monkeypatch):
    """Installs a fake client and store in place of the real ones."""

    def install(items=FOUND):
        client = FakeClient(items)
        store = FakeStore()
        monkeypatch.setattr(ingestion, "CompanyHouseClient", lambda: client)
        monkeypatch.setattr(ingestion, "CompanyHouseStorage", lambda: store)
        return client, store

    return install


def test_fetching_a_company_returns_the_search_results(wiring):
    wiring()

    assert ingestion.fetch_company("ACME Ltd") == FOUND


def test_fetching_a_company_searches_the_name_it_was_given(wiring):
    client, _ = wiring()

    ingestion.fetch_company("ACME Ltd")

    assert client.searched == ["ACME Ltd"]


def test_a_name_with_no_matches_fetches_an_empty_list(wiring):
    wiring(items=[])

    assert ingestion.fetch_company("Nonesuch Ltd") == []


def test_ingesting_a_company_caches_what_the_search_returned(wiring):
    _, store = wiring()

    ingestion.CompanyHouseIngestion().ingest_company("ACME Ltd")

    assert store.cached == [("ACME Ltd", FOUND)]


def test_ingesting_a_company_with_no_matches_still_caches(wiring):
    """The empty result is what stops the name being searched again."""
    _, store = wiring(items=[])

    ingestion.CompanyHouseIngestion().ingest_company("Nonesuch Ltd")

    assert store.cached == [("Nonesuch Ltd", [])]
