from external.companies_house.matching import (
    classify_status,
    find_best_match,
    normalize_company_name,
)
from external.companies_house.models import CompanySearchResult


def _candidate(title: str, company_number: str = "12345678") -> CompanySearchResult:
    return CompanySearchResult(company_number=company_number, title=title)


def test_normalize_strips_legal_suffix_and_punctuation():
    assert normalize_company_name("Acme, Ltd.") == "acme"
    assert normalize_company_name("Acme Limited") == "acme"
    assert normalize_company_name("ACME INC.") == "acme"


def test_exact_match_is_verified():
    candidates = [_candidate("Acme Ltd")]
    best, score = find_best_match("Acme Ltd", candidates)
    status = classify_status(best is not None, score)

    assert best.title == "Acme Ltd"
    assert status == "verified"


def test_legal_suffix_variance_still_verified():
    candidates = [_candidate("Acme Limited")]
    best, score = find_best_match("Acme Ltd", candidates)
    status = classify_status(best is not None, score)

    assert status == "verified"


def test_close_typo_matches_with_lower_confidence():
    candidates = [_candidate("Ancme Ltd")]
    best, score = find_best_match("Acme Ltd", candidates)
    status = classify_status(best is not None, score)

    assert best is not None
    assert status in ("verified", "low_confidence")


def test_unrelated_name_is_not_found():
    candidates = [_candidate("Globex Corporation")]
    best, score = find_best_match("Acme Ltd", candidates)
    status = classify_status(best is not None, score)

    assert status == "not_found"


def test_empty_candidate_list_is_not_found():
    best, score = find_best_match("Acme Ltd", [])
    status = classify_status(best is not None, score)

    assert best is None
    assert score == 0.0
    assert status == "not_found"


def test_best_match_picks_highest_scoring_candidate():
    candidates = [
        _candidate("Globex Corporation", company_number="1"),
        _candidate("Acme Ltd", company_number="2"),
    ]
    best, _ = find_best_match("Acme Ltd", candidates)

    assert best.company_number == "2"
