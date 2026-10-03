"""
bronze.raw_cv_texts -> raw_candidates, raw_work_experience, raw_skills.

Sends each CV text to Claude for structured extraction and lands the
result in the three entity tables, still as written by the candidate.
"""

from datetime import datetime, timezone

from dagster import asset, get_dagster_logger
from dotenv import load_dotenv
from pydantic import ValidationError

from bronze.rules.parsing import (
    categorize_skill,
)
from bronze.storage import (
    save_json_to_gcs,
)
from bronze.warehouse import (
    BRONZE_DATASET,
    PROJECT_ID,
    get_all_cv_texts,
    get_processed_submission_ids,
    insert_rows_to_bigquery,
)

load_dotenv()

from bronze.llm_extraction import extract_cv_data_with_claude

@asset(deps=["extract_raw_text"])
def extract_entities():
    """
    LLM Extraction 2: CV Extractor.
    Uses Claude Haiku to extract structured entities from each CV.
    No regex parsing, no SpaCy for companies or dates.
    Claude understands CV context and returns clean JSON.
    Loads into BigQuery Bronze raw_work_experience and raw_skills.

    Reads the current CV list directly from raw_cv_texts (not as a Dagster
    input from extract_raw_text) so this asset always processes the real,
    full set of CVs rather than whatever extract_raw_text's last run
    happened to return.
    """
    log = get_dagster_logger()

    work_experience_rows = []
    skills_rows = []
    candidate_rows = []

    existing_exp = get_processed_submission_ids("raw_work_experience")
    log.info(f"Already processed experiences: {len(existing_exp)}")

    all_cvs = get_all_cv_texts()
    log.info(f"CVs in raw_cv_texts: {len(all_cvs)}")

    for record in all_cvs:

        # skip non-technical profiles
        if record["profile_type"] == "non_technical":
            log.info(f"[SKIP non-technical] {record['submission_id']}")
            continue

        submission_id = record["submission_id"]

        # skip if already processed
        if submission_id in existing_exp:
            log.info(f"[SKIP] {submission_id}")
            continue

        raw_text = record["raw_text"]

        try:
            # call Claude to extract all entities
            log.info(f"[LLM Extraction] Extracting entities from {submission_id}...")
            cv_data = extract_cv_data_with_claude(raw_text)

            # Contact info — attributes, not .get()
            candidate_name = cv_data.candidate_name
            email = cv_data.email
            phone = cv_data.phone
            linkedin = cv_data.linkedin
            github = cv_data.github

            candidate_rows.append({
                "submission_id": submission_id,
                "candidate_name": candidate_name,
                "email": email,
                "phone": phone,
                "linkedin": linkedin,
                "github": github,
                "extracted_at": datetime.now(timezone.utc).isoformat(),
            })

            # Work experience — iterate over Pydantic models
            for idx, exp in enumerate(cv_data.work_experience):
                experience_row = {
                    "experience_id": f"{submission_id}_job{idx + 1}",
                    "submission_id": submission_id,
                    "company_name": exp.company_name,
                    "company_website": exp.company_website,
                    "job_title": exp.job_title,
                    "location": exp.location,
                    "start_date_raw": exp.start_date,
                    "end_date_raw": exp.end_date,
                    "description": exp.description,
                    "is_current": exp.is_current,
                }
                work_experience_rows.append(experience_row)

            # Skills
            for skill in cv_data.skills:
                skill_id = f"{submission_id}_{skill.lower().replace(' ', '_')}"
                skills_rows.append({
                    "skill_id": skill_id,
                    "submission_id": submission_id,
                    "skill_name": skill,
                    "skill_category": categorize_skill(skill),
                })

            # For the GCS backup, dump to dict
            save_json_to_gcs(
                {
                    "submission_id": submission_id,
                    **cv_data.model_dump(),
                    "extracted_at": datetime.now(timezone.utc).isoformat(),
                },
                f"cvs/extracted/entities/{submission_id}.json"
            )

            log.info(
                f"[OK] {submission_id} → "
                f"{len(cv_data.work_experience)} jobs, "
                f"{len(cv_data.skills)} skills"
            )

        except ValidationError as e:
            log.error(f"[FAIL] {submission_id}: {e}")

    if candidate_rows:
        insert_rows_to_bigquery(
            f"{PROJECT_ID}.{BRONZE_DATASET}.raw_candidates",
            candidate_rows,
        )
        log.info(f"Inserted {len(candidate_rows)} rows into raw_candidates")

    if work_experience_rows:
        insert_rows_to_bigquery(
            f"{PROJECT_ID}.{BRONZE_DATASET}.raw_work_experience",
            work_experience_rows,
        )
        log.info(f"Inserted {len(work_experience_rows)} rows into raw_work_experience")

    if skills_rows:
        insert_rows_to_bigquery(
            f"{PROJECT_ID}.{BRONZE_DATASET}.raw_skills",
            skills_rows,
        )
        log.info(f"Inserted {len(skills_rows)} rows into raw_skills")

    return {
        "candidates_count": len(candidate_rows),
        "work_experience_count": len(work_experience_rows),
        "skills_count": len(skills_rows),
    }