"""
bronze.raw_cv_texts -> raw_candidates, raw_work_experience, raw_skills

Structure: a pure core and a thin I/O shell.

    build_entity_rows()        pure - one CV's three sets of rows
    EntitiesStore              protocol - every read/write this needs
    BigQueryEntitiesStore      the only code here touching GCS and BigQuery
    run_extract_entities()     orchestration, with dependencies injected
    extract_entities           Dagster asset - wires the real ones

The store and the Claude call are injected, so the whole run works against
an in-memory fake with no BigQuery and no API calls.
"""

from datetime import datetime, timezone
from typing import Callable, Protocol

from dagster import asset, get_dagster_logger
from google.cloud import bigquery
from pydantic import ValidationError

from bronze.io.llm_extraction import extract_cv_data_with_claude
from bronze.rules.cv_analysis import categorize_skill
from bronze.schemas import ExtractedCV
from bronze.io.gcs_storage import save_json_to_gcs
from bronze.io.bigquery_persistence import (
    BRONZE_DATASET,
    PROJECT_ID,
    ensure_table,
    get_all_cv_texts,
    get_processed_submission_ids,
    insert_rows_to_bigquery,
)

CANDIDATES_TABLE = "raw_candidates"
WORK_EXPERIENCE_TABLE = "raw_work_experience"
SKILLS_TABLE = "raw_skills"

# Match the live tables. Bronze appends, so a table has to exist before the
# first insert - see ensure_table. Only raw_candidates enforces its keys at
# the database level; for the other two that job falls to the asset checks.
SCHEMAS: dict[str, list[bigquery.SchemaField]] = {
    CANDIDATES_TABLE: [
        bigquery.SchemaField("submission_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("candidate_name", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("email", "STRING"),
        bigquery.SchemaField("phone", "STRING"),
        bigquery.SchemaField("linkedin", "STRING"),
        bigquery.SchemaField("github", "STRING"),
        bigquery.SchemaField("extracted_at", "TIMESTAMP", mode="REQUIRED"),
    ],
    WORK_EXPERIENCE_TABLE: [
        bigquery.SchemaField("experience_id", "STRING"),
        bigquery.SchemaField("submission_id", "STRING"),
        bigquery.SchemaField("company_name", "STRING"),
        bigquery.SchemaField("job_title", "STRING"),
        # bronze keeps the date as the CV wrote it; silver parses it
        bigquery.SchemaField("start_date_raw", "STRING"),
        bigquery.SchemaField("end_date_raw", "STRING"),
        bigquery.SchemaField("description", "STRING"),
        bigquery.SchemaField("is_current", "BOOLEAN"),
        bigquery.SchemaField("location", "STRING"),
        bigquery.SchemaField("company_website", "STRING"),
    ],
    SKILLS_TABLE: [
        bigquery.SchemaField("skill_id", "STRING"),
        bigquery.SchemaField("submission_id", "STRING"),
        bigquery.SchemaField("skill_name", "STRING"),
        bigquery.SchemaField("skill_category", "STRING"),
    ],
}


# ── Pure core ─────────────────────────────────────────────────────────────
def build_entity_rows(
    submission_id: str,
    cv_data: ExtractedCV,
    extracted_at: datetime,
) -> tuple[dict, list[dict], list[dict]]:
    """
    Turns one extracted CV into its candidate row, work experience rows and
    skill rows. Pure: same inputs always give the same output.
    """
    timestamp = extracted_at.isoformat()

    candidate = {
        "submission_id": submission_id,
        "candidate_name": cv_data.candidate_name,
        "email": cv_data.email,
        "phone": cv_data.phone,
        "linkedin": cv_data.linkedin,
        "github": cv_data.github,
        "extracted_at": timestamp,
    }

    experiences = [
        {
            "experience_id": f"{submission_id}_job{index + 1}",
            "submission_id": submission_id,
            "company_name": exp.company_name,
            "company_website": exp.company_website,
            "job_title": exp.job_title,
            "location": exp.location,
            # bronze keeps the date as the CV wrote it; silver parses it
            "start_date_raw": exp.start_date,
            "end_date_raw": exp.end_date,
            "description": exp.description,
            "is_current": exp.is_current,
        }
        for index, exp in enumerate(cv_data.work_experience)
    ]

    skills = [
        {
            "skill_id": f"{submission_id}_{skill.lower().replace(' ', '_')}",
            "submission_id": submission_id,
            "skill_name": skill,
            "skill_category": categorize_skill(skill),
        }
        for skill in cv_data.skills
    ]

    return candidate, experiences, skills


# ── I/O boundary ──────────────────────────────────────────────────────────
class EntitiesStore(Protocol):
    """Everything the entity pipeline needs from BigQuery and GCS."""

    def read_cv_texts(self) -> list[dict]:
        """`raw_cv_texts` rows: {submission_id, profile_type, raw_text}."""

    def read_processed_submission_ids(self) -> set[str]:
        """The submission_ids already in raw_work_experience."""

    def insert_candidates(self, rows: list[dict]) -> None:
        """Appends rows to raw_candidates."""

    def insert_work_experience(self, rows: list[dict]) -> None:
        """Appends rows to raw_work_experience."""

    def insert_skills(self, rows: list[dict]) -> None:
        """Appends rows to raw_skills."""

    def archive_extraction(self, submission_id: str, payload: dict) -> None:
        """Keeps the raw extraction as JSON, before BigQuery."""


class BigQueryEntitiesStore:
    """EntitiesStore backed by BigQuery, with the JSON archive in GCS."""

    def read_cv_texts(self) -> list[dict]:
        return get_all_cv_texts()

    def read_processed_submission_ids(self) -> set[str]:
        return get_processed_submission_ids(WORK_EXPERIENCE_TABLE)

    def _insert(self, table: str, rows: list[dict]) -> None:
        table_id = f"{PROJECT_ID}.{BRONZE_DATASET}.{table}"
        ensure_table(table_id, SCHEMAS[table])
        insert_rows_to_bigquery(table_id, rows)

    def insert_candidates(self, rows: list[dict]) -> None:
        self._insert(CANDIDATES_TABLE, rows)

    def insert_work_experience(self, rows: list[dict]) -> None:
        self._insert(WORK_EXPERIENCE_TABLE, rows)

    def insert_skills(self, rows: list[dict]) -> None:
        self._insert(SKILLS_TABLE, rows)

    def archive_extraction(self, submission_id: str, payload: dict) -> None:
        save_json_to_gcs(payload, f"cvs/extracted/entities/{submission_id}.json")


# ── Orchestration (dependencies injected) ─────────────────────────────────
def run_extract_entities(
    store: EntitiesStore,
    *,
    extract: Callable[[str], ExtractedCV] = extract_cv_data_with_claude,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    report: Callable[[str], None] = lambda message: None,
) -> dict:
    """
    Extracts entities from every new technical CV and writes the three entity
    tables. The store, the extractor and the clock are injected so this runs
    with no BigQuery, no API calls and no Dagster.
    """
    already_processed = store.read_processed_submission_ids()
    report(f"Already processed experiences: {len(already_processed)}")

    cv_texts = store.read_cv_texts()
    report(f"CVs in raw_cv_texts: {len(cv_texts)}")

    candidate_rows: list[dict] = []
    work_experience_rows: list[dict] = []
    skills_rows: list[dict] = []
    extracted_at = now()

    for record in cv_texts:
        submission_id = record["submission_id"]

        if record["profile_type"] == "non_technical":
            report(f"[SKIP non-technical] {submission_id}")
            continue

        if submission_id in already_processed:
            report(f"[SKIP] {submission_id}")
            continue

        try:
            cv_data = extract(record["raw_text"])
        except ValidationError as e:
            report(f"[FAIL] {submission_id}: {e}")
            continue

        candidate, experiences, skills = build_entity_rows(
            submission_id, cv_data, extracted_at
        )
        candidate_rows.append(candidate)
        work_experience_rows.extend(experiences)
        skills_rows.extend(skills)

        store.archive_extraction(
            submission_id,
            {
                "submission_id": submission_id,
                **cv_data.model_dump(),
                "extracted_at": extracted_at.isoformat(),
            },
        )

        report(
            f"[OK] {submission_id} -> {len(experiences)} jobs, {len(skills)} skills"
        )

    if candidate_rows:
        store.insert_candidates(candidate_rows)
        report(f"Inserted {len(candidate_rows)} rows into {CANDIDATES_TABLE}")

    if work_experience_rows:
        store.insert_work_experience(work_experience_rows)
        report(
            f"Inserted {len(work_experience_rows)} rows into {WORK_EXPERIENCE_TABLE}"
        )

    if skills_rows:
        store.insert_skills(skills_rows)
        report(f"Inserted {len(skills_rows)} rows into {SKILLS_TABLE}")

    return {
        "candidates_count": len(candidate_rows),
        "work_experience_count": len(work_experience_rows),
        "skills_count": len(skills_rows),
    }


# ── ASSET: extract_entities ───────────────────────────────────────────────
@asset(deps=["extract_raw_text"])
def extract_entities():
    """
    Sends each CV's text to Claude and lands the structured result in
    raw_candidates, raw_work_experience and raw_skills, still as the
    candidate wrote it.

    Reads the CV list from raw_cv_texts rather than as a Dagster input, so it
    always sees the full current set rather than whatever extract_raw_text
    returned on its last run.
    """
    return run_extract_entities(
        BigQueryEntitiesStore(),
        report=get_dagster_logger().info,
    )
