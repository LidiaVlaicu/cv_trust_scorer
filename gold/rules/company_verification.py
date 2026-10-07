"""
The rules behind gold.signal_company_verification

Can the employer a candidate claims be found in the Companies House register?

Each employer carries one `status`:

    confirmed      the register holds a company with the same name
    partial_match  the register holds a similar name, not the same one
    unconfirmed    nothing in the register matches the name

There is no score and no threshold. The status follows from how the words of
the two names compare, so every verdict can be checked by eye.

Limitation: Companies House registers UK companies only, so this signal
fully verifies UK CVs. For an employer in another country `unconfirmed`
means this register cannot confirm it, not that the company is invented.
Name matching lives in external/companies_house/name_matching.py.
"""

from typing import Literal

VerificationStatus = Literal["confirmed", "partial_match", "unconfirmed"]

# How a name comparison becomes a verdict. A name that merely resembles a
# registered one is reported as partial_match rather than being counted as
# either confirmation or doubt.
_STATUS_BY_MATCH: dict[str, VerificationStatus] = {
    "exact": "confirmed",
    "partial": "partial_match",
    "different": "unconfirmed",
}


def classify_status(match: str) -> VerificationStatus:
    """The verdict for one employer, from how its name compared."""
    return _STATUS_BY_MATCH[match]
