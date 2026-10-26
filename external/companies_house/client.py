"""
REST client for the Company House API.
"""

import os

import requests
from dotenv import load_dotenv

from .models import (
    CompanySearchResponse,
    CompanySearchResult,
)

load_dotenv()

BASE_URL = "https://api.company-information.service.gov.uk"
SEARCH_ENDPOINT = "/search/companies"
TIMEOUT_SECONDS = 30


class CompanyHouseClient:
    """Client responsible for communicating with the Company House API."""

    def __init__(self) -> None:
        self.api_key = os.getenv("COMPANIES_HOUSE_API_KEY")

        if not self.api_key:
            raise ValueError("COMPANIES_HOUSE_API_KEY not found.")

    def search_company(
        self,
        company_name: str,
    ) -> CompanySearchResponse:

        response = requests.get(
            f"{BASE_URL}{SEARCH_ENDPOINT}",
            params={"q": company_name},
            auth=(self.api_key, ""),
            timeout=TIMEOUT_SECONDS,
        )

        response.raise_for_status()

        return parse_search_payload(response.json())


def parse_search_payload(payload: dict) -> CompanySearchResponse:
    """
    The search response as our own models.

    Only company_number and title are required; the rest of the fields are
    absent often enough in real results that they default to None. Kept apart
    from the request so the mapping can be checked without a network call.
    """
    companies = [
        CompanySearchResult(
            company_number=item["company_number"],
            title=item["title"],
            company_status=item.get("company_status"),
            company_type=item.get("company_type"),
            address_snippet=item.get("address_snippet"),
        )
        for item in payload.get("items", [])
    ]

    return CompanySearchResponse(
        items=companies,
        total_results=payload.get("total_results", 0),
    )
