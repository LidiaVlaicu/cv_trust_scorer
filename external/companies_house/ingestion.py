"""
Transformation utilities for Companies House data.
"""

from .client import CompanyHouseClient
from .models import CompanySearchResult
from .storage import CompanyHouseStorage


def fetch_company(
    company_name: str,
) -> list[CompanySearchResult]:
    """
    Search Companies House and return matching companies.
    """

    client = CompanyHouseClient()
    response = client.search_company(company_name)

    return response.items

class CompanyHouseIngestion:

    def __init__(self):

        self.client = CompanyHouseClient()
        self.store = CompanyHouseStorage()

    def ingest_company(
        self,
        company_name: str,
    ) -> None:

        response = self.client.search_company(company_name)

        self.store.insert_search_results(
            company_name,
            response.items,
        )