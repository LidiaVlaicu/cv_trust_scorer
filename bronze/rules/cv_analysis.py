"""
This module contains functions that analyze a CV after the text has been extracted.

It includes a profile classifier to determine if a CV belongs to a technical IT profile,
a skill categoriser to map normalized skill names to their respective categories,
and a compute metadata function (hash of the CV text).

"""

import hashlib

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


# ── Skill categoriser ─────────────────────────────────────────────────────
# Normalized (lowercase, stripped) skill name -> category. A single lookup
# table instead of per-category if/elif lists, so adding a skill is one line
# and matching is case-insensitive (the previous version compared exact
# strings, so "python" or "PostgreSQL" as extracted by Claude never matched
# "Python" / not present at all, and fell into "other").
_SKILL_CATEGORIES: dict[str, str] = {
    # languages
    "python": "language", "sql": "language", "scala": "language", "java": "language",
    "go": "language", "golang": "language", "rust": "language", "typescript": "language",
    "javascript": "language", "js": "language", "bash": "language", "shell": "language",
    "r": "language", "c++": "language", "c#": "language", "pyspark": "language",

    # cloud platforms & managed services
    "aws": "cloud", "gcp": "cloud", "google cloud": "cloud", "azure": "cloud",
    "s3": "cloud", "ec2": "cloud", "lambda": "cloud", "cloud run": "cloud",
    "dataflow": "cloud", "vertex ai": "cloud", "gcs": "cloud", "sagemaker": "cloud",
    "azure data factory": "cloud", "azure synapse": "cloud", "azure databricks": "cloud",

    # databases & warehouses
    "postgres": "database", "postgresql": "database", "mysql": "database",
    "mongodb": "database", "redis": "database", "elasticsearch": "database",
    "cassandra": "database", "bigquery": "database", "snowflake": "database",
    "databricks": "database", "redshift": "database", "athena": "database",

    # data engineering
    "spark": "data_engineering", "kafka": "data_engineering", "airflow": "data_engineering",
    "dbt": "data_engineering", "dagster": "data_engineering", "prefect": "data_engineering",
    "fivetran": "data_engineering", "airbyte": "data_engineering",
    "etl": "data_engineering", "elt": "data_engineering",

    # BI & analytics
    "tableau": "bi_analytics", "looker": "bi_analytics", "looker studio": "bi_analytics",
    "power bi": "bi_analytics", "powerbi": "bi_analytics", "qlik": "bi_analytics",
    "metabase": "bi_analytics", "superset": "bi_analytics", "excel": "bi_analytics",
    "dax": "bi_analytics",

    # ML & AI
    "machine learning": "ml_ai", "deep learning": "ml_ai", "tensorflow": "ml_ai",
    "pytorch": "ml_ai", "scikit-learn": "ml_ai", "sklearn": "ml_ai", "xgboost": "ml_ai",
    "huggingface": "ml_ai", "transformers": "ml_ai", "pandas": "ml_ai", "numpy": "ml_ai",
    "mlflow": "ml_ai", "llm": "ml_ai", "nlp": "ml_ai", "rag": "ml_ai",
    "langchain": "ml_ai", "llamaindex": "ml_ai", "openai": "ml_ai",
    "anthropic": "ml_ai", "claude": "ml_ai",

    # DevOps & infra
    "docker": "devops", "kubernetes": "devops", "k8s": "devops", "terraform": "devops",
    "helm": "devops", "ansible": "devops", "prometheus": "devops", "grafana": "devops",
    "github actions": "devops", "gitlab ci": "devops", "jenkins": "devops",
    "argocd": "devops", "ci/cd": "devops", "git": "devops", "github": "devops", "gitlab": "devops",

    # web frameworks
    "fastapi": "web", "django": "web", "flask": "web", "spring boot": "web",
    "express": "web", "nestjs": "web", "react": "web", "next.js": "web", "nextjs": "web",
    "vue": "web", "vue.js": "web", "angular": "web", "svelte": "web",
    "node.js": "web", "nodejs": "web", "graphql": "web", "rest": "web", "grpc": "web",

    # practices
    "agile": "practices", "scrum": "practices", "tdd": "practices",
    "system design": "practices", "distributed systems": "practices",
    "a/b testing": "practices", "ab testing": "practices", "a/b test": "practices",
}


def categorize_skill(skill: str) -> str:
    """
    Assigns a category to a technical skill via normalized lookup.
    Falls back to "other" for anything not in the known taxonomy
    (an open vocabulary is expected — "other" isn't itself a bug).
    """
    normalized = skill.strip().lower()
    return _SKILL_CATEGORIES.get(normalized, "other")



def compute_file_hash(file_bytes: bytes) -> str:
    """Content hash of a PDF, used to detect a changed CV between runs."""
    return hashlib.sha256(file_bytes).hexdigest()
