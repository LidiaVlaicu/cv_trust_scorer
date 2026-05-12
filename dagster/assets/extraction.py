import re
import json
import fitz
import anthropic
from dagster import asset, get_dagster_logger
from google.cloud import storage, bigquery
from datetime import datetime, timezone
import os
from dotenv import load_dotenv

load_dotenv()

BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")
PROJECT_ID = os.getenv("BIGQUERY_PROJECT_ID")
BRONZE_DATASET = "cv_trust_scorer_bronze"

TECHNICAL_KEYWORDS = [
    "python", "sql", "spark", "docker", "kubernetes", "data engineer",
    "software engineer", "machine learning", "backend", "frontend",
    "devops", "cloud", "api", "tensorflow", "pytorch", "bigquery",
    "airflow", "dbt", "kafka", "terraform", "react", "typescript",
    "data scientist", "ml engineer", "data analyst", "research engineer",
    "full stack", "microservices", "ci/cd", "github actions", "mlops",
]


# ── Profile classifier ────────────────────────────────────────────────────
def classify_profile(text):
    """
    Checks if a CV belongs to a technical IT profile.
    Counts how many technical keywords appear in the text.
    If 3 or more keywords found → technical profile.
    3 is the minimum threshold to avoid false positives
    (a non-technical CV might mention 1 or 2 tech words by chance).
    """
    text_lower = text.lower()
    matches = []

    for kw in TECHNICAL_KEYWORDS:
        if kw in text_lower:
            matches.append(kw)

    if len(matches) >= 3:
        return "technical"
    else:
        return "non_technical"


# ── Seniority detector ────────────────────────────────────────────────────
def detect_seniority(text):
    """
    Detects the seniority level from CV text.
    Checks for keywords in order from highest to lowest seniority.
    Returns the first match found.
    """
    text_lower = text.lower()

    staff_keywords = ["staff", "principal", "director", "vp", "head of"]
    senior_keywords = ["senior", " sr "]
    junior_keywords = ["junior", "graduate", "trainee"]
    mid_keywords = ["mid ", "associate"]

    for word in staff_keywords:
        if word in text_lower:
            return "Staff"

    for word in senior_keywords:
        if word in text_lower:
            return "Senior"

    for word in junior_keywords:
        if word in text_lower:
            return "Junior"

    for word in mid_keywords:
        if word in text_lower:
            return "Mid"

    return "Unknown"


# ── Skill categoriser ─────────────────────────────────────────────────────
def categorize_skill(skill):
    """
    Assigns a category to a technical skill.
    Returns: language, cloud, framework, devops, or other.
    """
    languages = [
        "Python", "SQL", "Scala", "Java", "Go", "Rust",
        "TypeScript", "JavaScript", "Bash", "R", "PySpark"
    ]
    cloud = [
        "AWS", "GCP", "Azure", "BigQuery", "Snowflake",
        "Databricks", "Redshift", "Athena"
    ]
    frameworks = [
        "Spark", "Kafka", "Airflow", "dbt", "Dagster",
        "TensorFlow", "PyTorch", "scikit-learn", "FastAPI",
        "Django", "React", "Vue.js", "Next.js", "LangChain",
        "LlamaIndex", "HuggingFace", "MLflow"
    ]
    devops = [
        "Docker", "Kubernetes", "Terraform", "GitHub Actions",
        "ArgoCD", "Helm", "Prometheus", "Grafana"
    ]

    if skill in languages:
        return "language"
    elif skill in cloud:
        return "cloud"
    elif skill in frameworks:
        return "framework"
    elif skill in devops:
        return "devops"
    else:
        return "other"


# ── Claude extraction agent ───────────────────────────────────────────────
def extract_cv_data_with_claude(raw_text):
    """
    Agent 2: CV Extractor.
    Sends the CV text to Claude Haiku.
    Claude extracts all structured data and returns clean JSON.
    Much more accurate than regex or SpaCy for CV parsing.
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    prompt = f"""Extract structured data from this CV text.
Return ONLY valid JSON, no explanation, no markdown, no code blocks.

{{
  "candidate_name": "full name from CV",
  "email": "email address or empty string",
  "phone": "phone number or empty string",
  "linkedin": "linkedin url or empty string",
  "github": "github url or empty string",
  "work_experience": [
    {{
      "job_title": "exact job title as written in CV",
      "company_name": "exact company name as written in CV",
      "company_website": "company website url or empty string",
      "location": "city and country or empty string",
      "start_date": "Month Year format or empty string",
      "end_date": "Month Year format or Present",
      "is_current": true or false,
      "description": "all bullet points joined with | separator"
    }}
  ],
  "skills": ["skill1", "skill2", "skill3"]
}}

Rules:
- work_experience must contain ONLY actual jobs
- A job entry must have a clear job title AND company name
- Do not include companies mentioned inside bullet points
- skills must be technical skills only
- Return exactly the number of jobs present in the CV
- Do not invent data, only extract what is written

CV TEXT:
{raw_text}"""

    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    response_text = message.content[0].text.strip()

    # remove markdown code blocks if Claude added them
    if response_text.startswith("```"):
        response_text = re.sub(r"```json\n?|```\n?", "", response_text).strip()

    cv_data = json.loads(response_text)
    return cv_data


# ── GCS helpers ───────────────────────────────────────────────────────────
def list_pdfs_in_gcs(folder):
    """Returns a list of all PDF blobs in the given GCS folder."""
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    all_blobs = bucket.list_blobs(prefix=f"cvs/raw/{folder}/")
    pdf_blobs = []
    for blob in all_blobs:
        if blob.name.endswith(".pdf"):
            pdf_blobs.append(blob)
    return pdf_blobs


def download_pdf_from_gcs(blob):
    """Downloads a PDF from GCS and returns its bytes."""
    return blob.download_as_bytes()


def save_json_to_gcs(data, gcs_path):
    """Saves a Python dictionary as a JSON file to GCS."""
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(gcs_path)
    blob.upload_from_string(
        json.dumps(data, indent=2, default=str),
        content_type="application/json"
    )


# ── BigQuery helpers ──────────────────────────────────────────────────────
def insert_rows_to_bigquery(table_id, rows):
    """Inserts a list of rows into a BigQuery table."""
    client = bigquery.Client(project=PROJECT_ID)
    errors = client.insert_rows_json(table_id, rows)
    if errors:
        raise Exception(f"BigQuery insert errors: {errors}")


def get_processed_ids(table, id_column="submission_id"):
    """
    Returns a set of IDs already present in a BigQuery table.
    Used to skip CVs that have already been processed.
    If the table does not exist or query fails, returns empty set
    so the pipeline starts fresh without crashing.
    """
    client = bigquery.Client(project=PROJECT_ID)
    query = f"SELECT {id_column} FROM `{PROJECT_ID}.{BRONZE_DATASET}.{table}`"

    try:
        rows = client.query(query).result()
        existing_ids = set()
        for row in rows:
            existing_ids.add(row[id_column])
        return existing_ids

    except Exception:
        return set()


# ── ASSET 1: extract_raw_text ─────────────────────────────────────────────
@asset
def extract_raw_text():
    """
    Reads each PDF from GCS.
    Extracts raw text with PyMuPDF.
    Classifies profile type and detects seniority.
    Saves raw text JSON to GCS.
    Loads into BigQuery Bronze raw_candidates table.
    """
    log = get_dagster_logger()
    results = []

    # get IDs already in BigQuery to avoid duplicates
    existing = get_processed_ids("raw_candidates")
    log.info(f"Already processed: {len(existing)} CVs")

    for folder in ["inconsistent", "legitimate"]:
        blobs = list_pdfs_in_gcs(folder)
        log.info(f"Found {len(blobs)} PDFs in {folder}/")

        for blob in blobs:
            filename = blob.name.split("/")[-1]
            submission_id = filename.replace(".pdf", "")

            # skip if already in BigQuery
            if submission_id in existing:
                log.info(f"[SKIP] {submission_id}")
                continue

            try:
                # download PDF from GCS
                pdf_bytes = download_pdf_from_gcs(blob)

                # extract text with PyMuPDF
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                raw_text = ""
                for page in doc:
                    raw_text = raw_text + page.get_text()
                doc.close()

                # skip empty PDFs
                if not raw_text.strip():
                    log.warning(f"Empty text: {filename}")
                    continue

                # classify and detect seniority
                profile_type = classify_profile(raw_text)
                seniority = detect_seniority(raw_text)

                # save raw text to GCS as backup
                save_json_to_gcs(
                    {
                        "submission_id": submission_id,
                        "raw_text": raw_text,
                        "profile_type": profile_type,
                        "seniority_detected": seniority,
                        "extracted_at": datetime.now(timezone.utc).isoformat(),
                    },
                    f"cvs/extracted/raw_text/{submission_id}.json"
                )

                # prepare row for BigQuery
                row = {
                    "submission_id": submission_id,
                    "profile_type": profile_type,
                    "seniority_detected": seniority,
                    "cv_file_path": f"gs://{BUCKET_NAME}/{blob.name}",
                    "submission_timestamp": datetime.now(timezone.utc).isoformat(),
                    "raw_text": raw_text,
                    "folder": folder,
                }
                results.append(row)

                log.info(f"[OK] {submission_id}")

            except Exception as e:
                log.error(f"[FAIL] {filename}: {e}")

    # insert all new rows into BigQuery at once
    if len(results) > 0:
        table_id = f"{PROJECT_ID}.{BRONZE_DATASET}.raw_candidates"
        insert_rows_to_bigquery(table_id, results)
        log.info(f"Inserted {len(results)} rows into raw_candidates")

    return results


# ── ASSET 2: extract_entities (AI Agent) ─────────────────────────────────
@asset
def extract_entities(extract_raw_text):
    """
    Agent 2: CV Extractor.
    Uses Claude Haiku to extract structured entities from each CV.
    No regex parsing, no SpaCy for companies or dates.
    Claude understands CV context and returns clean JSON.
    Loads into BigQuery Bronze raw_work_experience and raw_skills.
    """
    log = get_dagster_logger()

    work_experience_rows = []
    skills_rows = []

    # get IDs already processed to avoid duplicates
    existing_exp = get_processed_ids("raw_work_experience")
    log.info(f"Already processed experiences: {len(existing_exp)}")

    for record in extract_raw_text:

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
            log.info(f"[AGENT] Extracting entities from {submission_id}...")
            cv_data = extract_cv_data_with_claude(raw_text)

            # extract contact info from Claude response
            candidate_name = cv_data.get("candidate_name", "")
            email = cv_data.get("email", "")
            phone = cv_data.get("phone", "")
            linkedin = cv_data.get("linkedin", "")
            github = cv_data.get("github", "")

            # build work experience rows
            work_experience_list = cv_data.get("work_experience", [])
            for idx in range(len(work_experience_list)):
                exp = work_experience_list[idx]
                experience_row = {
                    "experience_id": submission_id + "_job" + str(idx + 1),
                    "submission_id": submission_id,
                    "company_name": exp.get("company_name", ""),
                    "company_website": exp.get("company_website", ""),
                    "job_title": exp.get("job_title", ""),
                    "location": exp.get("location", ""),
                    "start_date_raw": exp.get("start_date", ""),
                    "end_date_raw": exp.get("end_date", "Present"),
                    "description": exp.get("description", ""),
                    "is_current": exp.get("is_current", False),
                }
                work_experience_rows.append(experience_row)

            # build skills rows
            skills_list = cv_data.get("skills", [])
            for skill in skills_list:
                skill_id = submission_id + "_" + skill.lower().replace(" ", "_")
                skill_row = {
                    "skill_id": skill_id,
                    "submission_id": submission_id,
                    "skill_name": skill,
                    "skill_category": categorize_skill(skill),
                }
                skills_rows.append(skill_row)

            # save extracted entities to GCS as backup
            save_json_to_gcs(
                {
                    "submission_id": submission_id,
                    "candidate_name": candidate_name,
                    "email": email,
                    "phone": phone,
                    "linkedin": linkedin,
                    "github": github,
                    "work_experience": work_experience_list,
                    "skills": skills_list,
                    "extracted_at": datetime.now(timezone.utc).isoformat(),
                },
                f"cvs/extracted/entities/{submission_id}.json"
            )

            log.info(
                f"[OK] {submission_id} → "
                f"{len(work_experience_list)} jobs, "
                f"{len(skills_list)} skills"
            )

        except Exception as e:
            log.error(f"[FAIL] {submission_id}: {e}")

    # insert work experience into BigQuery
    if len(work_experience_rows) > 0:
        table_id = f"{PROJECT_ID}.{BRONZE_DATASET}.raw_work_experience"
        insert_rows_to_bigquery(table_id, work_experience_rows)
        log.info(f"Inserted {len(work_experience_rows)} rows into raw_work_experience")

    # insert skills into BigQuery
    if len(skills_rows) > 0:
        table_id = f"{PROJECT_ID}.{BRONZE_DATASET}.raw_skills"
        insert_rows_to_bigquery(table_id, skills_rows)
        log.info(f"Inserted {len(skills_rows)} rows into raw_skills")

    return {
        "work_experience_count": len(work_experience_rows),
        "skills_count": len(skills_rows),
    }