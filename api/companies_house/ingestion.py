"""
Transformation utilities for Companies House data.
"""

from companies_house.client import CompaniesHouseClient
from companies_house.models import CompanySearchResult


def fetch_company(
    company_name: str,
) -> list[CompanySearchResult]:
    """
    Search Companies House and return matching companies.
    """

    client = CompaniesHouseClient()

    response = client.search_company(company_name)

    return response.items