"""
The rules behind gold.signal_company_verification

The verdict: given how closely a CV's employer matches a name in the Companies
House register, can the employer be considered real?

Name matching itself lives in external/companies_house/name_matching.py, next to
the API client whose response shape it reads. Only the verdict is here, with
the other gold thresholds.
"""

from typing import Literal

VERIFIED_THRESHOLD = 85
LOW_CONFIDENCE_THRESHOLD = 60

VerificationStatus = Literal["verified", "low_confidence", "not_found"]


def classify_status(candidate_found: bool, score: float) -> VerificationStatus:
    """
    A name-similarity score as a verification status.

    A score below LOW_CONFIDENCE_THRESHOLD is reported as not_found rather
    than as a weak match: a name that different cannot be evidence either way.
    """
    if not candidate_found:
        return "not_found"
    if score >= VERIFIED_THRESHOLD:
        return "verified"
    if score >= LOW_CONFIDENCE_THRESHOLD:
        return "low_confidence"
    return "not_found"
