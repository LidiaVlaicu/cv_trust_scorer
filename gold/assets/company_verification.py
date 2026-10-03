import os
import time
from datetime import datetime, timezone

import requests
from dagster import asset, get_dagster_logger
from google.cloud import bigquery

from api.company_house.ingestion import fetch_company
from api.company_house.matching import (
    classify_status,
    find_best_match,
    normalize_company_name,
)
from api.company_house.models import CompanyVerificationResult
from api.company_house.storage import CompanyHouseStorage

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
BRONZE_DATASET = os.getenv("BQ_DATASET_BRONZE")

LIVE_API_SLEEP_SECONDS = 0.5


def _get_work_experience_companies() -> list[dict]:
    """Returns [{experience_id, submission_id, company_name}] from bronze."""
    client = bigquery.Client(project=PROJECT_ID)
    query = f"""
        SELECT experience_id, submission_id, company_name
        FROM `{PROJECT_ID}.{BRONZE_DATASET}.raw_work_experience`
    """
    rows = client.query(query).result()
    return [dict(row) for row in rows]


# ── ASSET 3: verify_companies ──────────────────────────────────────────────
@asset(deps=["extract_entities"])
def verify_companies():
    """
    Signal: company verification.

    For each work-experience row, checks whether the claimed employer can be
    found in the Companies House register under a plausible name match.
    Search results are cached by normalized company name so CVs that repeat
    the same employer (common in the synthetic set) don't re-hit the API.
    """
    log = get_dagster_logger()
    store = CompanyHouseStorage()

    companies = _get_work_experience_companies()
    already_verified = store.get_verified_experience_ids()
    log.info(f"Already verified: {len(already_verified)} experiences")

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
                candidates = fetch_company(company_name)
            except requests.RequestException as e:
                log.error(f"[FAIL] search for '{company_name}': {e}")
                continue

            store.insert_search_results(company_name, candidates)
            time.sleep(LIVE_API_SLEEP_SECONDS)
        else:
            candidates = cached

        best_match, score = find_best_match(company_name, candidates)
        status = classify_status(best_match is not None, score)

        results.append(
            CompanyVerificationResult(
                submission_id=row["submission_id"],
                experience_id=experience_id,
                company_name_cv=company_name,
                matched_company_number=(
                    best_match.company_number if best_match else None
                ),
                matched_company_name=best_match.title if best_match else None,
                match_score=score,
                status=status,
                verified_at=datetime.now(timezone.utc),
            )
        )

        log.info(f"[{status.upper()}] {company_name} (score={score:.0f})")

    if results:
        store.insert_verification_results(results)
        log.info(f"Inserted {len(results)} verification rows")

    return {"verified_count": len(results)}
