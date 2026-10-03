"""
Data-quality checks on the bronze tables, as Dagster asset checks.

These run automatically after the asset that writes each table and fail the
run when the data is unusable. That is the difference from the script this
replaces: it printed warnings nobody read, and silver would happily consume
broken bronze.

What is checked, and what deliberately is not
---------------------------------------------
Bronze stores what arrived and corrects nothing, so these do NOT check whether
a value is plausible - that is silver's job. They check only that the rows can
be used at all:

    keys        a NULL or blank id breaks every downstream join
    content     a CV with no text, or a role with no employer, cannot be read
    uniqueness  a duplicated id silently multiplies rows in every join
    integrity   an entity row whose submission_id is absent from raw_cv_texts
                is an orphan, which the delete-and-reprocess path could create

Columns that are legitimately empty are NOT checked, because a check that
always fails gets ignored. Measured on the current 300 CVs:

    github            59% empty  - most candidates list none
    company_website    3% empty  - not always on a CV
    location         0.3% empty

Severity: a broken key or a duplicate is ERROR, because silver cannot be
trusted afterwards. Missing content is WARN - one unreadable CV among 300 is
worth seeing, not worth stopping the pipeline for.
"""

import os

from dagster import AssetCheckResult, AssetCheckSeverity, asset_check
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID")
BRONZE_DATASET = os.getenv("BQ_DATASET_BRONZE")


def _client() -> bigquery.Client:
    return bigquery.Client(project=PROJECT_ID)


def _scalar(query: str) -> int:
    return list(_client().query(query).result())[0][0]


def _table(name: str) -> str:
    return f"`{PROJECT_ID}.{BRONZE_DATASET}.{name}`"


def _blank_count(table: str, column: str) -> int:
    """Rows where `column` is NULL or an empty/whitespace string."""
    return _scalar(
        f"SELECT COUNTIF({column} IS NULL OR TRIM({column}) = '') FROM {_table(table)}"
    )


def _duplicate_count(table: str, column: str) -> int:
    """How many values of `column` appear more than once."""
    return _scalar(f"""
        SELECT COUNT(*) FROM (
            SELECT {column} FROM {_table(table)}
            GROUP BY {column} HAVING COUNT(*) > 1
        )
    """)


def _orphan_count(table: str) -> int:
    """Rows whose submission_id has no matching CV in raw_cv_texts."""
    return _scalar(f"""
        SELECT COUNT(*) FROM {_table(table)} t
        LEFT JOIN {_table("raw_cv_texts")} c USING (submission_id)
        WHERE c.submission_id IS NULL
    """)


def _result(failures: dict[str, int], *, severity: AssetCheckSeverity, subject: str):
    """One AssetCheckResult from {description: offending row count}."""
    offenders = {name: count for name, count in failures.items() if count}
    return AssetCheckResult(
        passed=not offenders,
        severity=severity,
        metadata={"offending_rows": offenders or "none", "checked": subject},
        description=(
            f"{subject}: " + ", ".join(f"{n} ({c} rows)" for n, c in offenders.items())
            if offenders else f"{subject}: all rows usable"
        ),
    )


# ── raw_cv_texts, written by extract_raw_text ─────────────────────────────
@asset_check(asset="extract_raw_text", blocking=True)
def raw_cv_texts_is_usable():
    """Every CV needs an id, text to read, and a single row of its own."""
    return _result(
        {
            "submission_id blank": _blank_count("raw_cv_texts", "submission_id"),
            "raw_text blank": _blank_count("raw_cv_texts", "raw_text"),
            "content_hash blank": _blank_count("raw_cv_texts", "content_hash"),
            "duplicate submission_id": _duplicate_count("raw_cv_texts", "submission_id"),
        },
        severity=AssetCheckSeverity.ERROR,
        subject="raw_cv_texts",
    )


# ── the three entity tables, written by extract_entities ──────────────────
@asset_check(asset="extract_entities", blocking=True)
def entity_keys_are_sound():
    """
    Ids must be present and unique, and must point at a real CV.

    An orphan row is the specific failure the reprocessing path can cause:
    delete_cv_data removes a changed CV from every bronze table, so a partial
    failure between the delete and the re-insert would leave entities behind.
    """
    return _result(
        {
            "raw_candidates: blank submission_id":
                _blank_count("raw_candidates", "submission_id"),
            "raw_candidates: duplicate submission_id":
                _duplicate_count("raw_candidates", "submission_id"),
            "raw_work_experience: blank experience_id":
                _blank_count("raw_work_experience", "experience_id"),
            "raw_work_experience: duplicate experience_id":
                _duplicate_count("raw_work_experience", "experience_id"),
            "raw_skills: blank skill_id":
                _blank_count("raw_skills", "skill_id"),
            "raw_skills: duplicate skill_id":
                _duplicate_count("raw_skills", "skill_id"),
            "raw_candidates: orphaned": _orphan_count("raw_candidates"),
            "raw_work_experience: orphaned": _orphan_count("raw_work_experience"),
            "raw_skills: orphaned": _orphan_count("raw_skills"),
        },
        severity=AssetCheckSeverity.ERROR,
        subject="entity keys and references",
    )


@asset_check(asset="extract_entities")
def entity_content_is_present():
    """
    The fields silver cannot work without.

    WARN rather than ERROR: a single role with no company name is a bad
    extraction worth seeing, not a reason to stop the whole pipeline.
    Optional columns (github, company_website, location) are not checked.
    """
    return _result(
        {
            "raw_candidates: candidate_name blank":
                _blank_count("raw_candidates", "candidate_name"),
            "raw_work_experience: company_name blank":
                _blank_count("raw_work_experience", "company_name"),
            "raw_work_experience: job_title blank":
                _blank_count("raw_work_experience", "job_title"),
            # bronze keeps the date exactly as the CV wrote it ("August 2017"),
            # so the column is start_date_raw; parsing happens in silver
            "raw_work_experience: start_date_raw blank":
                _blank_count("raw_work_experience", "start_date_raw"),
            "raw_skills: skill_name blank":
                _blank_count("raw_skills", "skill_name"),
        },
        severity=AssetCheckSeverity.WARN,
        subject="entity content",
    )


@asset_check(asset="extract_entities")
def every_cv_produced_entities():
    """
    A CV that yielded no work experience and no skills means the LLM returned
    nothing usable for it. Pydantic validation accepts an empty list, so this
    is the only place such a CV would be noticed.
    """
    silent = _scalar(f"""
        SELECT COUNT(*) FROM {_table("raw_cv_texts")} c
        WHERE NOT EXISTS (SELECT 1 FROM {_table("raw_work_experience")} w
                          WHERE w.submission_id = c.submission_id)
          AND NOT EXISTS (SELECT 1 FROM {_table("raw_skills")} s
                          WHERE s.submission_id = c.submission_id)
    """)
    total = _scalar(f"SELECT COUNT(*) FROM {_table('raw_cv_texts')}")
    return AssetCheckResult(
        passed=silent == 0,
        severity=AssetCheckSeverity.WARN,
        metadata={"cvs_with_no_entities": silent, "cvs_total": total},
        description=(
            f"{silent} of {total} CVs produced no work experience and no skills"
            if silent else f"all {total} CVs produced entities"
        ),
    )
