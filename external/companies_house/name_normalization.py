"""
Reducing a company name to a comparable form.

Shared by two callers: the search cache keys on the normalized name, and the
gold verification rules compare normalized names. Keeping it in one place
means the cache and the comparison cannot disagree about what counts as the
same name.
"""

import re

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
