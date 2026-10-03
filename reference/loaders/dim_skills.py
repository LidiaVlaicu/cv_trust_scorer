"""
Loads the reviewed skills taxonomy into the `dim_skills` reference table.

    skills_taxonomy_review.csv  (reviewed, version-controlled)
                 |
                 v  parse + validate (pure, see taxonomy_csv.py)
          silver.dim_skills      (alias -> canonical_skill)

The CSV is the single source of truth, so this is a full refresh: the table is
replaced with exactly what the file says. That matters for correctness — an
incremental merge would leave aliases from an earlier version of the taxonomy
behind, still pointing at canonical skills the file no longer agrees with.
Edit the CSV, rerun this script; history lives in git.

Run with:  python -m reference.loaders.dim_skills
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery

from reference import SKILLS_TAXONOMY_CSV
from reference.parsing.taxonomy_csv import parse_taxonomy_csv, to_bigquery_rows

load_dotenv()

TAXONOMY_CSV_PATH = SKILLS_TAXONOMY_CSV

DIM_SKILLS_TABLE = "dim_skills"
DIM_SKILLS_SCHEMA = [
    bigquery.SchemaField("alias", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("canonical_skill", "STRING", mode="REQUIRED"),
]


def load_dim_skills(csv_path: Path = TAXONOMY_CSV_PATH) -> int:
    """Replaces `dim_skills` with the aliases in `csv_path`. Returns the row count."""
    aliases = parse_taxonomy_csv(csv_path.read_text(encoding="utf-8"))
    rows = to_bigquery_rows(aliases)

    client = bigquery.Client(project=os.getenv("GCP_PROJECT_ID"))
    table_id = f"{client.project}.{os.getenv('BQ_DATASET_SILVER')}.{DIM_SKILLS_TABLE}"

    job_config = bigquery.LoadJobConfig(
        schema=DIM_SKILLS_SCHEMA,
        write_disposition="WRITE_TRUNCATE",
    )
    client.load_table_from_json(rows, table_id, job_config=job_config).result()

    canonical_count = len({entry.canonical_skill for entry in aliases})
    print(
        f"Loaded {len(rows)} aliases covering {canonical_count} canonical skills "
        f"into {table_id}"
    )
    return len(rows)


if __name__ == "__main__":
    load_dim_skills()
