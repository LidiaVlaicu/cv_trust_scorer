"""
silver.silver_work_experience -> gold.signal_company_verification

Structure: a thin I/O shell around the pure matching rules.

    CompanyVerificationStore    protocol - every read/write this needs
    run_verify_companies()      orchestration, with dependencies injected
    verify_companies            Dagster asset - wires the real ones

The store, the Companies House search and the sleep are injected, so the
run function works against an in-memory fake with no BigQuery and no API
calls. Every rule - how names compare and what the comparison means -
lives in gold/rules/company_verification.py.
"""

import time
from datetime import datetime, timezone
from typing import Callable, Protocol

import requests
from dagster import asset, get_dagster_logger
from google.cloud import bigquery

from external.companies_house.ingestion import fetch_company
from external.companies_house.models import (
    CompanySearchResult,
    CompanyVerificationResult,
)
from external.companies_house.name_normalization import normalize_company_name
from external.companies_house.storage import CompanyHouseStorage
from gold.rules.company_verification import classify_status, find_match

LIVE_API_SLEEP_SECONDS = 0.5

SIGNAL_TABLE = "signal_company_verification"
# One row per role, appended rather than replaced, so the table has to exist
# before the first insert. Matches the live table.
SIGNAL_SCHEMA = [
    bigquery.SchemaField("submission_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("experience_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("company_name_cv", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("matched_company_number", "STRING"),
    bigquery.SchemaField("matched_company_name", "STRING"),
    bigquery.SchemaField("status", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("verified_at", "TIMESTAMP", mode="REQUIRED"),
]


# ── I/O boundary ──────────────────────────────────────────────────────────
class CompanyVerificationStore(Protocol):
    """Everything the company signal needs from the warehouse."""

    def read_work_experience_companies(self) -> list[dict]:
        """`silver_work_experience` rows: {experience_id, submission_id,
        company_name}."""

    def get_verified_experience_ids(self) -> set[str]:
        """The experience_ids already written to the signal table."""

    def get_cached_search(
        self, company_query_normalized: str
    ) -> list[CompanySearchResult] | None:
        """Cached search: None on a miss, [] on a cached NOT_FOUND."""

    def insert_search_results(
        self, company_query: str, search_results: list[CompanySearchResult]
    ) -> None:
        """Caches one search under its normalized query."""

    def insert_verification_results(
        self, results: list[CompanyVerificationResult]
    ) -> None:
        """Appends the verification rows to the signal table."""


# ── Orchestration (dependencies injected) ─────────────────────────────────
def run_verify_companies(
    store: CompanyVerificationStore,
    *,
    search: Callable[[str], list[CompanySearchResult]] = fetch_company,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    sleep: Callable[[float], None] = time.sleep,
    report: Callable[[str], None] = lambda message: None,
) -> dict:
    """
    Matches every unverified employer against Companies House and writes the
    signal rows. The store, the search, the clock and the sleep are injected
    so this runs with no BigQuery, no API calls and no Dagster.
    """
    companies = store.read_work_experience_companies()
    already_verified = store.get_verified_experience_ids()
    report(f"Already verified: {len(already_verified)} experiences")

    results: list[CompanyVerificationResult] = []

    for row in companies:
        experience_id = row["experience_id"]

        if experience_id in already_verified:
            continue

        company_name = row["company_name"]
        normalized = normalize_company_name(company_name)

        cached = store.get_cached_search(normalized)

        if cached is None:
            try:
                candidates = search(company_name)
            except requests.RequestException as e:
                report(f"[FAIL] search for '{company_name}': {e}")
                continue

            store.insert_search_results(company_name, candidates)
            sleep(LIVE_API_SLEEP_SECONDS)
        else:
            candidates = cached

        best_match, match = find_match(company_name, candidates)
        status = classify_status(match)

        results.append(
            CompanyVerificationResult(
                submission_id=row["submission_id"],
                experience_id=experience_id,
                company_name_cv=company_name,
                matched_company_number=(
                    best_match.company_number if best_match else None
                ),
                matched_company_name=best_match.title if best_match else None,
                status=status,
                verified_at=now(),
            )
        )

        report(f"[{status.upper()}] {company_name}")

    if results:
        store.insert_verification_results(results)
        report(f"Inserted {len(results)} verification rows")

    return {"verified_count": len(results)}


# ── ASSET: verify_companies ───────────────────────────────────────────────
@asset(deps=["silver_work_experience"])
def verify_companies():
    """
    Signal: company verification.

    For each work-experience row, checks whether the claimed employer can be
    found in the Companies House register under a plausible name match.
    Search results are cached by normalized company name so CVs that repeat
    the same employer don't re-hit the API.
    """
    return run_verify_companies(
        CompanyHouseStorage(verification_schema=SIGNAL_SCHEMA),
        report=get_dagster_logger().info,
    )
