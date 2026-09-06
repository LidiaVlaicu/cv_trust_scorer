"""
Pydantic models for the Company House API.
"""

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