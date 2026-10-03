"""
Pure name-matching and classification logic for company verification.

No I/O here — everything is a plain function over in-memory data, so it can
be unit tested without mocking GCP or the Companies House API.
"""

import re
from typing import Literal

from rapidfuzz import fuzz

from .models import CompanySearchResult

VERIFIED_THRESHOLD = 85
LOW_CONFIDENCE_THRESHOLD = 60

VerificationStatus = Literal["verified", "low_confidence", "not_found"]

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


def find_best_match(
    query_name: str,
    candidates: list[CompanySearchResult],
) -> tuple[CompanySearchResult | None, float]:
    """Returns the candidate with the highest name-similarity score, and that score."""
    if not candidates:
        return None, 0.0

    normalized_query = normalize_company_name(query_name)

    best_candidate = None
    best_score = 0.0

    for candidate in candidates:
        score = fuzz.token_sort_ratio(
            normalized_query,
            normalize_company_name(candidate.title),
        )
        if score > best_score:
            best_score = score
            best_candidate = candidate

    return best_candidate, best_score


def classify_status(candidate_found: bool, score: float) -> VerificationStatus:
    """Maps a match outcome to a verification status using the module thresholds."""
    if not candidate_found:
        return "not_found"
    if score >= VERIFIED_THRESHOLD:
        return "verified"
    if score >= LOW_CONFIDENCE_THRESHOLD:
        return "low_confidence"
    return "not_found"
