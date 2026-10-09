"""
The company verification verdict, and an end-to-end test of the pipeline
against an in-memory fake store — no BigQuery, no Companies House calls, no
credentials.
"""

from datetime import datetime, timezone

import pytest
import requests

from external.companies_house.models import CompanySearchResult
from external.companies_house.name_normalization import normalize_company_name
from gold.assets.signal_company_verification import run_verify_companies
from gold.rules.company_verification import classify_status, compare_names, find_match

FIXED_TIME = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _result(title: str, company_number: str = "01234567") -> CompanySearchResult:
    return CompanySearchResult(company_number=company_number, title=title)


# ── comparing two names ───────────────────────────────────────────────────
def test_the_same_name_is_exact():
    assert compare_names("Acme Ltd", "Acme Ltd") == "exact"


def test_a_legal_suffix_variant_is_exact():
    """"Acme Ltd" and "Acme Limited" are the same company."""
    assert compare_names("Acme Ltd", "Acme Limited") == "exact"


def test_word_order_does_not_matter():
    assert compare_names("Smith Consulting", "Consulting Smith") == "exact"


def test_a_shorter_name_inside_a_longer_one_is_partial():
    assert compare_names("Monzo", "Monzo Bank Limited") == "partial"
    assert compare_names("Monzo Bank Limited", "Monzo") == "partial"


def test_an_unrelated_name_is_different():
    assert compare_names("Acme Ltd", "Globex Corporation") == "different"


def test_a_typo_is_different_not_partial():
    """No fuzzy matching: one wrong letter is a different word."""
    assert compare_names("Acme Ltd", "Ancme Ltd") == "different"


def test_a_name_with_no_words_left_is_different():
    assert compare_names("", "Acme Ltd") == "different"
    assert compare_names("Ltd", "Acme Ltd") == "different"


# ── picking a candidate ───────────────────────────────────────────────────
def test_an_exact_match_wins_over_a_partial_one():
    candidates = [
        _result("Acme Holdings Limited", company_number="1"),
        _result("Acme Limited", company_number="2"),
    ]
    best, match = find_match("Acme", candidates)

    assert best.company_number == "2"
    assert match == "exact"


def test_a_partial_candidate_is_returned_when_there_is_no_exact_one():
    best, match = find_match("Monzo", [_result("Monzo Bank Limited")])

    assert best.title == "Monzo Bank Limited"
    assert match == "partial"


def test_no_candidate_at_all_is_different():
    best, match = find_match("Acme Ltd", [])

    assert best is None
    assert match == "different"


def test_candidates_that_all_differ_return_nothing():
    best, match = find_match("Acme Ltd", [_result("Globex Corporation")])

    assert best is None
    assert match == "different"


# ── the verdict ───────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "match, expected",
    [
        ("exact", "confirmed"),
        ("partial", "partial_match"),
        ("different", "unconfirmed"),
    ],
)
def test_a_name_comparison_maps_to_a_status(match, expected):
    assert classify_status(match) == expected


def test_a_similar_name_is_neither_confirmation_nor_doubt():
    """partial_match is its own answer, not a weaker form of confirmed."""
    assert classify_status("partial") == "partial_match"


class FakeStore:
    """In-memory CompanyVerificationStore. Records what would be written."""

    def __init__(
        self,
        companies: list[dict],
        verified: set[str] | None = None,
        cache: dict[str, list[CompanySearchResult]] | None = None,
    ) -> None:
        self._companies = companies
        self._verified = verified or set()
        self._cache = cache or {}
        self.written: list = []
        self.searches_cached: list[str] = []

    def read_work_experience_companies(self) -> list[dict]:
        return self._companies

    def get_verified_experience_ids(self) -> set[str]:
        return self._verified

    def get_cached_search(self, company_query_normalized: str):
        return self._cache.get(company_query_normalized)

    def insert_search_results(self, company_query, search_results) -> None:
        self.searches_cached.append(company_query)
        self._cache[normalize_company_name(company_query)] = search_results

    def insert_verification_results(self, results) -> None:
        self.written.extend(results)


COMPANIES = [
    {"experience_id": "cv_1_job1", "submission_id": "cv_1", "company_name": "Monzo Bank Ltd"},
    {"experience_id": "cv_2_job1", "submission_id": "cv_2", "company_name": "Totally Fake Co"},
]

REGISTER = {
    "monzo bank": [_result("MONZO BANK LIMITED")],
    "totally fake": [],
}


def _search(company_name: str) -> list[CompanySearchResult]:
    return REGISTER.get(normalize_company_name(company_name), [])


def _run(store: FakeStore, **kwargs):
    sleeps: list[float] = []
    result = run_verify_companies(
        store,
        search=kwargs.pop("search", _search),
        now=lambda: FIXED_TIME,
        sleep=sleeps.append,
        **kwargs,
    )
    return result, sleeps


def test_confirms_a_real_company_and_leaves_a_fake_one_unconfirmed():
    store = FakeStore(COMPANIES)
    result, _ = _run(store)

    assert result["verified_count"] == 2
    by_id = {row.experience_id: row for row in store.written}

    assert by_id["cv_1_job1"].status == "confirmed"
    assert by_id["cv_1_job1"].matched_company_name == "MONZO BANK LIMITED"

    assert by_id["cv_2_job1"].status == "unconfirmed"
    assert by_id["cv_2_job1"].matched_company_number is None


def test_a_shortened_employer_name_is_a_partial_match():
    """A CV writing "Monzo" for "Monzo Bank Limited" is neither confirmed nor doubted."""
    store = FakeStore(
        [{"experience_id": "cv_9_job1", "submission_id": "cv_9", "company_name": "Monzo"}],
        cache={"monzo": [_result("MONZO BANK LIMITED")]},
    )
    _run(store)

    assert store.written[0].status == "partial_match"
    assert store.written[0].matched_company_name == "MONZO BANK LIMITED"


def test_skips_experiences_already_verified():
    store = FakeStore(COMPANIES, verified={"cv_1_job1"})
    result, _ = _run(store)

    assert result["verified_count"] == 1
    assert [row.experience_id for row in store.written] == ["cv_2_job1"]


def test_a_cached_search_does_not_hit_the_api_or_sleep():
    store = FakeStore(
        [COMPANIES[0]],
        cache={"monzo bank": [_result("MONZO BANK LIMITED")]},
    )

    def _must_not_be_called(company_name: str):
        raise AssertionError(f"searched for {company_name} despite a cached result")

    result, sleeps = _run(store, search=_must_not_be_called)

    assert result["verified_count"] == 1
    assert store.searches_cached == []
    assert sleeps == []


def test_the_same_employer_is_searched_once_across_cvs():
    """Two CVs claiming the same employer should cost one API call."""
    store = FakeStore([
        COMPANIES[0],
        {
            "experience_id": "cv_9_job1",
            "submission_id": "cv_9",
            "company_name": "Monzo Bank Limited",
        },
    ])
    result, sleeps = _run(store)

    assert result["verified_count"] == 2
    assert store.searches_cached == ["Monzo Bank Ltd"]
    assert len(sleeps) == 1


def test_a_failed_search_skips_the_row_and_keeps_going():
    store = FakeStore(COMPANIES)

    def _failing_search(company_name: str):
        if company_name == "Monzo Bank Ltd":
            raise requests.RequestException("timeout")
        return _search(company_name)

    reported: list[str] = []
    result, _ = _run(store, search=_failing_search, report=reported.append)

    assert result["verified_count"] == 1
    assert [row.experience_id for row in store.written] == ["cv_2_job1"]
    assert any("[FAIL]" in message for message in reported)


def test_every_row_carries_the_injected_timestamp():
    store = FakeStore(COMPANIES)
    _run(store)

    assert {row.verified_at for row in store.written} == {FIXED_TIME}


def test_nothing_is_written_when_everything_is_already_verified():
    store = FakeStore(COMPANIES, verified={"cv_1_job1", "cv_2_job1"})
    result, _ = _run(store)

    assert result["verified_count"] == 0
    assert store.written == []
