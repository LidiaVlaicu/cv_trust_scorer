import re
import json
import fitz
import anthropic
import hashlib
from dagster import asset, get_dagster_logger
from google.cloud import storage, bigquery
from datetime import datetime, timezone
import os
from dotenv import load_dotenv
from pydantic import ValidationError
from orchestration.assets.schemas import ExtractedCV

load_dotenv()

def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value

BUCKET_NAME = _require_env("GCS_BUCKET_NAME")
PROJECT_ID = _require_env("GCP_PROJECT_ID")
BRONZE_DATASET = _require_env("BQ_DATASET_BRONZE")

TECHNICAL_KEYWORDS = [
    # Roles
    "software engineer", "data engineer", "data scientist", "data analyst",
    "ml engineer", "machine learning engineer", "ai engineer",
    "analytics engineer", "bi analyst", "business intelligence",
    "backend engineer", "frontend engineer", "full stack", "fullstack",
    "devops engineer", "sre", "platform engineer", "cloud engineer",
    "solutions architect", "tech lead", "staff engineer", "principal engineer",

    # Languages
    "python", "sql", "java", "scala", "go", "golang", "rust",
    "typescript", "javascript", "c++", "c#", "bash",

    # Cloud platforms
    "aws", "gcp", "google cloud", "azure",

    # Cloud services (the ones that actually appear on CVs)
    "s3", "ec2", "lambda", "redshift", "sagemaker",
    "bigquery", "cloud run", "dataflow", "vertex ai", "gcs",
    "azure data factory", "azure synapse", "azure databricks", "azure devops",
    "power bi", "dax", "power query", "azure data studio",

    # Data engineering
    "spark", "pyspark", "kafka", "airflow", "dagster", "prefect",
    "dbt", "snowflake", "databricks", "fivetran", "airbyte",
    "etl", "elt", "data warehouse", "data lake", "lakehouse",
    "delta lake", "iceberg", "medallion architecture",

    # Databases
    "postgres", "postgresql", "mysql", "mongodb", "redis",
    "elasticsearch", "cassandra",

    # BI & analytics
    "tableau", "looker", "looker studio", "qlik", "metabase",
    "superset", "excel",

    # ML & AI
    "machine learning", "deep learning", "tensorflow", "pytorch",
    "scikit-learn", "xgboost", "huggingface", "transformers",
    "pandas", "numpy", "mlflow", "mlops",
    "llm", "nlp", "computer vision", "embeddings", "vector database",
    "rag", "langchain", "openai", "anthropic", "claude",
    "prompt engineering", "fine-tuning", "agentic",

    # DevOps & infra
    "docker", "kubernetes", "k8s", "terraform", "helm", "ansible",
    "prometheus", "grafana", "datadog",

    # CI/CD & version control
    "git", "github", "gitlab", "github actions", "gitlab ci",
    "jenkins", "argocd", "ci/cd",

    # Web — backend
    "backend", "api", "rest", "graphql", "grpc", "microservices",
    "serverless", "fastapi", "django", "flask", "spring boot",
    "express", "nestjs",

    # Web — frontend
    "frontend", "react", "next.js", "vue", "angular", "svelte",
    "tailwind", "node.js",

    # Validation, quality, observability
    "pydantic", "great expectations", "data quality",
    "data observability",

    # Practices
    "agile", "scrum", "tdd", "system design", "distributed systems",
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


# ── Claude extraction ───────────────────────────────────────────────
def extract_cv_data_with_claude(raw_text):
    """
    LLM Extraction 2: CV Extractor.
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

    cv_data = ExtractedCV.model_validate_json(response_text)
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

def compute_file_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()

def delete_cv_data(submission_id: str):
    """
    Removes all bronze records for a given submission_id.
    Uses parameterized SQL to avoid injection on names with apostrophes.
    """
    client = bigquery.Client(project=PROJECT_ID)
    tables = ["raw_cv_texts", "raw_candidates", "raw_work_experience", "raw_skills"]

    for table in tables:
        query = f"""
            DELETE FROM `{PROJECT_ID}.{BRONZE_DATASET}.{table}`
            WHERE submission_id = @submission_id
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("submission_id", "STRING", submission_id),
            ]
        )
        client.query(query, job_config=job_config).result()

def get_processed_versions(table, id_col="submission_id", hash_col="content_hash"):
    """
    Returns {submission_id: content_hash} of already-processed CVs.
    Returns empty dict if table doesn't exist or query fails.
    """
    client = bigquery.Client(project=PROJECT_ID)
    query = f"""
        SELECT {id_col}, {hash_col}
        FROM `{PROJECT_ID}.{BRONZE_DATASET}.{table}`
    """
    try:
        rows = client.query(query).result()
        return {row[id_col]: row[hash_col] for row in rows}
    except Exception:
        return {}

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
    
    # Now returns dict: {submission_id: content_hash}
    existing = get_processed_versions("raw_cv_texts")
    log.info(f"Already processed: {len(existing)} CVs")
    
    for folder in ["inconsistent", "legitimate"]:
        blobs = list_pdfs_in_gcs(folder)
        
        for blob in blobs:
            filename = blob.name.split("/")[-1]
            submission_id = filename.replace(".pdf", "")
            
            try:
                pdf_bytes = download_pdf_from_gcs(blob)
                current_hash = compute_file_hash(pdf_bytes)
                
                # Three cases
                if submission_id in existing:
                    if existing[submission_id] == current_hash:
                        # Unchanged: skip
                        log.info(f"[SKIP unchanged] {submission_id}")
                        continue
                    else:
                        # Changed: delete old, then reprocess
                        log.info(f"[REPROCESS changed] {submission_id}")
                        delete_cv_data(submission_id)
                
                # Process (new or changed)
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                raw_text = ""
                for page in doc:
                    raw_text += page.get_text()
                doc.close()
                
                if not raw_text.strip():
                    log.warning(f"Empty text: {filename}")
                    continue
                
                profile_type = classify_profile(raw_text)
                
                row = {
                    "submission_id": submission_id,
                    "content_hash": current_hash,  # new field
                    "profile_type": profile_type,
                    "cv_file_path": f"gs://{BUCKET_NAME}/{blob.name}",
                    "submission_timestamp": datetime.now(timezone.utc).isoformat(),
                    "raw_text": raw_text,
                    "folder": folder,
                }
                results.append(row)
                log.info(f"[OK] {submission_id}")
                
            except Exception as e:
                log.error(f"[FAIL] {filename}: {e}")
    
    if results:
        table_id = f"{PROJECT_ID}.{BRONZE_DATASET}.raw_cv_texts"
        insert_rows_to_bigquery(table_id, results)
        log.info(f"Inserted {len(results)} rows")
    
    return results
# ── ASSET 2: extract_entities (LLM Extraction) ─────────────────────────────────
@asset
def extract_entities(extract_raw_text):
    """
    LLM Extraction 2: CV Extractor.
    Uses Claude Haiku to extract structured entities from each CV.
    No regex parsing, no SpaCy for companies or dates.
    Claude understands CV context and returns clean JSON.
    Loads into BigQuery Bronze raw_work_experience and raw_skills.
    """
    log = get_dagster_logger()

    work_experience_rows = []
    skills_rows = []
    candidate_rows = []

    existing_exp = get_processed_versions("raw_work_experience")
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