"""
Pydantic models for the Company House API.
"""

from datetime import datetime

from pydantic import BaseModel


class CompanySearchResult(BaseModel):
    company_number: str
    title: str
    company_status: str | None = None
    company_type: str | None = None
    address_snippet: str | None = None


class CompanySearchResponse(BaseModel):
    items: list[CompanySearchResult] = []
    total_results: int = 0


class CompanyVerificationResult(BaseModel):
    """Outcome of matching one CV work-experience entry against Companies House."""

    submission_id: str
    experience_id: str
    company_name_cv: str
    matched_company_number: str | None = None
    matched_company_name: str | None = None
    status: str
    verified_at: datetime