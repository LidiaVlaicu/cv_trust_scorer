from datetime import datetime, UTC
import os

from google.cloud import bigquery

from .matching import normalize_company_name
from .models import CompanySearchResult, CompanyVerificationResult


class CompanyHouseStorage:
    """Persists Company House responses and verification results into BigQuery."""

    def __init__(self) -> None:
        self.client = bigquery.Client(
            project=os.getenv("GCP_PROJECT_ID")
        )

        bronze_dataset = os.getenv("BQ_DATASET_BRONZE")
        gold_dataset = os.getenv("BQ_DATASET_GOLD")

        self.search_table_id = (
            f"{self.client.project}.{bronze_dataset}."
            "companies_house_search_results"
        )
        self.verification_table_id = (
            f"{self.client.project}.{gold_dataset}."
            "signal_company_verification"
        )

    def insert_search_results(
        self,
        company_query: str,
        search_results: list[CompanySearchResult],
    ) -> None:
        """
        Caches a Companies House search under its normalized query.

        Writes a NOT_FOUND sentinel row when there are zero results, so a
        fake/unfindable company name is recorded as "already searched" and
        isn't re-queried against the live API on every future run.
        """

        retrieved_at = datetime.now(UTC).isoformat()
        company_query_normalized = normalize_company_name(company_query)

        if not search_results:
            rows = [
                {
                    "company_query": company_query,
                    "company_query_normalized": company_query_normalized,
                    "company_number": None,
                    "company_name": None,
                    "company_status": "NOT_FOUND",
                    "company_type": None,
                    "address_snippet": None,
                    "retrieved_at": retrieved_at,
                }
            ]
        else:
            rows = [
                {
                    "company_query": company_query,
                    "company_query_normalized": company_query_normalized,
                    "company_number": result.company_number,
                    "company_name": result.title,
                    "company_status": result.company_status,
                    "company_type": result.company_type,
                    "address_snippet": result.address_snippet,
                    "retrieved_at": retrieved_at,
                }
                for result in search_results
            ]

        errors = self.client.insert_rows_json(
            self.search_table_id,
            rows,
        )

        if errors:
            raise RuntimeError(errors)

    def get_cached_search(
        self,
        company_query_normalized: str,
    ) -> list[CompanySearchResult] | None:
        """
        Returns None on a cache miss (never searched), [] on a cached
        NOT_FOUND, or the cached candidate rows otherwise.
        """
        query = f"""
            SELECT company_number, company_name, company_status,
                   company_type, address_snippet
            FROM `{self.search_table_id}`
            WHERE company_query_normalized = @company_query_normalized
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter(
                    "company_query_normalized", "STRING", company_query_normalized
                ),
            ]
        )
        rows = list(self.client.query(query, job_config=job_config).result())

        if not rows:
            return None

        if len(rows) == 1 and rows[0]["company_status"] == "NOT_FOUND":
            return []

        return [
            CompanySearchResult(
                company_number=row["company_number"],
                title=row["company_name"],
                company_status=row["company_status"],
                company_type=row["company_type"],
                address_snippet=row["address_snippet"],
            )
            for row in rows
        ]

    def insert_verification_results(
        self,
        results: list[CompanyVerificationResult],
    ) -> None:
        if not results:
            return

        rows = [
            {
                "submission_id": result.submission_id,
                "experience_id": result.experience_id,
                "company_name_cv": result.company_name_cv,
                "matched_company_number": result.matched_company_number,
                "matched_company_name": result.matched_company_name,
                "match_score": result.match_score,
                "status": result.status,
                "verified_at": result.verified_at.isoformat(),
            }
            for result in results
        ]

        errors = self.client.insert_rows_json(
            self.verification_table_id,
            rows,
        )

        if errors:
            raise RuntimeError(errors)

    def get_verified_experience_ids(self) -> set[str]:
        query = f"SELECT experience_id FROM `{self.verification_table_id}`"
        try:
            rows = self.client.query(query).result()
            return {row["experience_id"] for row in rows}
        except Exception:
            return set()