"""
Name matching against the Companies House register. The verdict these scores
feed into is tested in tests/gold/test_signal_company_verification.py.
"""

from external.companies_house.name_matching import find_best_match, normalize_company_name
from external.companies_house.models import CompanySearchResult


def _candidate(title: str, company_number: str = "12345678") -> CompanySearchResult:
    return CompanySearchResult(company_number=company_number, title=title)


def test_normalize_strips_legal_suffix_and_punctuation():
    assert normalize_company_name("Acme, Ltd.") == "acme"
    assert normalize_company_name("Acme Limited") == "acme"
    assert normalize_company_name("ACME INC.") == "acme"


def test_an_exact_name_scores_full_marks():
    best, score = find_best_match("Acme Ltd", [_candidate("Acme Ltd")])

    assert best.title == "Acme Ltd"
    assert score == 100


def test_a_legal_suffix_variant_still_scores_full_marks():
    """"Acme Ltd" and "Acme Limited" are the same company."""
    _, score = find_best_match("Acme Ltd", [_candidate("Acme Limited")])

    assert score == 100


def test_a_typo_scores_below_full_marks_but_still_matches():
    best, score = find_best_match("Acme Ltd", [_candidate("Ancme Ltd")])

    assert best is not None
    assert 0 < score < 100


def test_an_unrelated_name_scores_low():
    _, score = find_best_match("Acme Ltd", [_candidate("Globex Corporation")])

    assert score < 60


def test_an_empty_candidate_list_scores_zero():
    best, score = find_best_match("Acme Ltd", [])

    assert best is None
    assert score == 0.0


def test_best_match_picks_highest_scoring_candidate():
    candidates = [
        _candidate("Globex Corporation", company_number="1"),
        _candidate("Acme Ltd", company_number="2"),
    ]
    best, _ = find_best_match("Acme Ltd", candidates)

    assert best.company_number == "2"
