"""
Tests for the Companies House client: the key it refuses to start without,
and the mapping from the search payload onto our own models.

The request itself is not exercised - only the two parts that can be wrong
without the network being involved.
"""

import pytest

from external.companies_house.client import CompanyHouseClient, parse_search_payload

ITEM = {"company_number": "01234567", "title": "ACME LTD"}


def test_a_client_without_an_api_key_refuses_to_start(monkeypatch):
    """Failing here beats a 401 on every lookup later."""
    monkeypatch.delenv("COMPANIES_HOUSE_API_KEY", raising=False)

    with pytest.raises(ValueError, match="COMPANIES_HOUSE_API_KEY"):
        CompanyHouseClient()


def test_an_empty_api_key_counts_as_missing(monkeypatch):
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "")

    with pytest.raises(ValueError, match="COMPANIES_HOUSE_API_KEY"):
        CompanyHouseClient()


def test_a_client_keeps_the_key_it_was_given(monkeypatch):
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "a-key")

    assert CompanyHouseClient().api_key == "a-key"


def test_a_payload_with_no_items_is_an_empty_response():
    parsed = parse_search_payload({})

    assert parsed.items == []
    assert parsed.total_results == 0


def test_the_required_fields_are_carried_across():
    parsed = parse_search_payload({"items": [ITEM], "total_results": 1})

    assert parsed.items[0].company_number == "01234567"
    assert parsed.items[0].title == "ACME LTD"
    assert parsed.total_results == 1


def test_optional_fields_absent_from_the_payload_become_none():
    parsed = parse_search_payload({"items": [ITEM]})

    assert parsed.items[0].company_status is None
    assert parsed.items[0].company_type is None
    assert parsed.items[0].address_snippet is None


def test_optional_fields_present_in_the_payload_are_kept():
    parsed = parse_search_payload(
        {"items": [{**ITEM, "company_status": "active", "company_type": "ltd"}]}
    )

    assert parsed.items[0].company_status == "active"
    assert parsed.items[0].company_type == "ltd"


def test_every_item_in_the_payload_is_mapped():
    parsed = parse_search_payload(
        {"items": [ITEM, {"company_number": "7654321", "title": "OTHER LTD"}]}
    )

    assert len(parsed.items) == 2


# ── the request itself ────────────────────────────────────────────────────
class FakeResponse:
    def __init__(self, payload, status_error=None):
        self._payload = payload
        self._status_error = status_error

    def raise_for_status(self):
        if self._status_error:
            raise self._status_error

    def json(self):
        return self._payload


@pytest.fixture
def request_to_api(monkeypatch):
    """Replaces requests.get so no call leaves the machine."""
    import external.companies_house.client as module

    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "a-key")

    def install(payload=None, status_error=None):
        calls = []

        def fake_get(url, params=None, auth=None, timeout=None):
            calls.append(
                {"url": url, "params": params, "auth": auth, "timeout": timeout}
            )
            return FakeResponse(payload or {"items": [ITEM]}, status_error)

        monkeypatch.setattr(module.requests, "get", fake_get)
        return calls

    return install


def test_a_search_returns_the_mapped_results(request_to_api):
    request_to_api()

    found = CompanyHouseClient().search_company("ACME Ltd")

    assert found.items[0].company_number == "01234567"


def test_the_company_name_is_sent_as_the_query(request_to_api):
    calls = request_to_api()

    CompanyHouseClient().search_company("ACME Ltd")

    assert calls[0]["params"] == {"q": "ACME Ltd"}


def test_the_api_key_is_sent_as_basic_auth_with_no_password(request_to_api):
    calls = request_to_api()

    CompanyHouseClient().search_company("ACME Ltd")

    assert calls[0]["auth"] == ("a-key", "")


def test_the_request_carries_a_timeout(request_to_api):
    """Without one a hung API would stall the whole asset indefinitely."""
    calls = request_to_api()

    CompanyHouseClient().search_company("ACME Ltd")

    assert calls[0]["timeout"] is not None


def test_an_error_status_is_raised_rather_than_parsed(request_to_api):
    request_to_api(status_error=RuntimeError("503"))

    with pytest.raises(RuntimeError):
        CompanyHouseClient().search_company("ACME Ltd")
