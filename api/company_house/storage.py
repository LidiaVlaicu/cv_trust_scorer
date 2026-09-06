from datetime import datetime, UTC
import os

from google.cloud import bigquery

from .models import CompanySearchResult


class CompanyHouseStorage:
    """Persists Company House responses into BigQuery."""

    def __init__(self) -> None:
        self.client = bigquery.Client(
            project=os.getenv("GCP_PROJECT_ID")
        )

        dataset = os.getenv("BQ_DATASET_BRONZE")

        self.table_id = (
            f"{self.client.project}.{dataset}."
            "companies_house_search_results"
        )

    def insert_search_results(
        self,
        company_query: str,
        search_results: list[CompanySearchResult],
    ) -> None:

        rows = []

        retrieved_at = datetime.now(UTC).isoformat()

        for result in search_results:

            rows.append(
                {
                    "company_query": company_query,
                    "company_number": result.company_number,
                    "company_name": result.title,
                    "company_status": result.company_status,
                    "company_type": result.company_type,
                    "address_snippet": result.address_snippet,
                    "retrieved_at": retrieved_at,
                }
            )

        errors = self.client.insert_rows_json(
            self.table_id,
            rows,
        )

        if errors:
            raise RuntimeError(errors)