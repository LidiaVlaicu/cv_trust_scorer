"""
Name matching against the Companies House register. The verdict these
outcomes feed into is tested in tests/gold/test_signal_company_verification.py.
"""

from external.companies_house.models import CompanySearchResult
from external.companies_house.name_matching import (
    compare_names,
    find_match,
    normalize_company_name,
)


def _candidate(title: str, company_number: str = "12345678") -> CompanySearchResult:
    return CompanySearchResult(company_number=company_number, title=title)


# ── normalizing ───────────────────────────────────────────────────────────
def test_normalize_strips_legal_suffix_and_punctuation():
    assert normalize_company_name("Acme, Ltd.") == "acme"
    assert normalize_company_name("Acme Limited") == "acme"
    assert normalize_company_name("ACME INC.") == "acme"


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


def test_an_empty_name_is_different():
    assert compare_names("", "Acme Ltd") == "different"
    assert compare_names("Ltd", "Acme Ltd") == "different"


# ── picking a candidate ───────────────────────────────────────────────────
def test_an_exact_candidate_is_returned():
    best, match = find_match("Acme Ltd", [_candidate("Acme Limited")])

    assert best.title == "Acme Limited"
    assert match == "exact"


def test_an_exact_match_wins_over_a_partial_one():
    candidates = [
        _candidate("Acme Holdings Limited", company_number="1"),
        _candidate("Acme Limited", company_number="2"),
    ]
    best, match = find_match("Acme", candidates)

    assert best.company_number == "2"
    assert match == "exact"


def test_a_partial_candidate_is_returned_when_there_is_no_exact_one():
    best, match = find_match("Monzo", [_candidate("Monzo Bank Limited")])

    assert best.title == "Monzo Bank Limited"
    assert match == "partial"


def test_no_candidate_at_all_is_different():
    best, match = find_match("Acme Ltd", [])

    assert best is None
    assert match == "different"


def test_candidates_that_all_differ_return_nothing():
    best, match = find_match("Acme Ltd", [_candidate("Globex Corporation")])

    assert best is None
    assert match == "different"
