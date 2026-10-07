"""
Pure name matching against the Companies House register.

How two names compare, not what the comparison means: the verdict lives in
gold/rules/company_verification.py.

There is no similarity score and no cut-off. Names are compared by their
words after normalizing, which gives three outcomes a person can check by
eye: the same words, one name's words contained in the other's, or neither.

No I/O here — everything is a plain function over in-memory data, so it can
be unit tested without mocking GCP or the Companies House API.
"""

import re
from typing import Literal

from .models import CompanySearchResult

MatchKind = Literal["exact", "partial", "different"]

_LEGAL_SUFFIXES = (
    "limited", "ltd", "llc", "inc", "incorporated",
    "plc", "corp", "corporation", "co", "gmbh", "llp",
)
_SUFFIX_PATTERN = re.compile(
    r"\b(" + "|".join(_LEGAL_SUFFIXES) + r")\b\.?"
)
_PUNCTUATION_PATTERN = re.compile(r"[^\w\s]")
_WHITESPACE_PATTERN = re.compile(r"\s+")


def normalize_company_name(name: str) -> str:
    """Lowercase, strip punctuation and common legal suffixes, collapse whitespace."""
    normalized = name.lower()
    normalized = _PUNCTUATION_PATTERN.sub(" ", normalized)
    normalized = _SUFFIX_PATTERN.sub(" ", normalized)
    normalized = _WHITESPACE_PATTERN.sub(" ", normalized).strip()
    return normalized


def compare_names(cv_name: str, register_name: str) -> MatchKind:
    """
    How a CV's employer compares with a register entry.

    "exact"     the same words, in any order
                ("Monzo Bank Ltd" / "MONZO BANK LIMITED")
    "partial"   one name's words are all present in the other
                ("Monzo" / "Monzo Bank Limited")
    "different" neither
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
