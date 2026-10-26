"""
The rules behind gold.signal_company_verification

Can the employer a candidate claims be found in the Companies House register?

Names are compared by their words, so each employer carries one `status`:

    confirmed      the register holds a company with the same name
    partial_match  the register holds a similar name, not the same one
    unconfirmed    nothing in the register matches the name

Limitation: Companies House registers UK companies only, so this signal
fully verifies UK CVs. For an employer in another country `unconfirmed`
means this register cannot confirm it, not that the company is invented.

This module is the pure core: the name comparison and the verdict, with no
network and no warehouse. Normalizing a name is shared with the search cache,
so it lives in external/companies_house/name_normalization.py. The I/O shell
lives in gold/assets/signal_company_verification.py.
"""

from typing import Literal

from external.companies_house.models import CompanySearchResult
from external.companies_house.name_normalization import normalize_company_name

MatchKind = Literal["exact", "partial", "different"]
VerificationStatus = Literal["confirmed", "partial_match", "unconfirmed"]

_STATUS_BY_MATCH: dict[MatchKind, VerificationStatus] = {
    "exact": "confirmed",
    "partial": "partial_match",
    "different": "unconfirmed",
}


def compare_names(cv_name: str, register_name: str) -> MatchKind:
    """
    How a CV's employer compares with a register entry.

    "exact"     the same words, in any order
                ("Monzo Bank Ltd" / "MONZO BANK LIMITED")
    "partial"   one name's words are all present in the other
                ("Monzo" / "Monzo Bank Limited")
    "different" neither, including a typo - there is no fuzzy matching
    """
    cv_words = set(normalize_company_name(cv_name).split())
    register_words = set(normalize_company_name(register_name).split())

    if not cv_words or not register_words:
        return "different"
    if cv_words == register_words:
        return "exact"
    if cv_words <= register_words or register_words <= cv_words:
        return "partial"
    return "different"


def find_match(
    cv_name: str,
    candidates: list[CompanySearchResult],
) -> tuple[CompanySearchResult | None, MatchKind]:
    """
    The best candidate for a CV's employer, and how it compares.

    An exact match wins outright; otherwise the first partial match is
    returned. With no candidate at all the result is (None, "different").
    """
    partial: CompanySearchResult | None = None

    for candidate in candidates:
        match = compare_names(cv_name, candidate.title)
        if match == "exact":
            return candidate, "exact"
        if match == "partial" and partial is None:
            partial = candidate

    if partial is not None:
        return partial, "partial"
    return None, "different"


def classify_status(match: MatchKind) -> VerificationStatus:
    """The verdict for one employer, from how its name compared."""
    return _STATUS_BY_MATCH[match]
