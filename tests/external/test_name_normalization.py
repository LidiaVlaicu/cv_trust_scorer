"""
Reducing a company name to a comparable form. The comparison itself is a gold
rule, tested in tests/gold/test_signal_company_verification.py.
"""

from external.companies_house.name_normalization import normalize_company_name


def test_normalize_strips_legal_suffix_and_punctuation():
    assert normalize_company_name("Acme, Ltd.") == "acme"
    assert normalize_company_name("Acme Limited") == "acme"
    assert normalize_company_name("ACME INC.") == "acme"


def test_normalize_collapses_whitespace_and_lowercases():
    assert normalize_company_name("  MONZO   BANK  ") == "monzo bank"


def test_a_name_that_is_only_a_legal_suffix_normalizes_to_nothing():
    assert normalize_company_name("Ltd.") == ""
