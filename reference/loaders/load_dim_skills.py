"""
Loads the reviewed skills taxonomy into `silver.dim_skills`.

Full refresh: an incremental merge would leave aliases from an earlier version
of the taxonomy behind, still pointing at canonical skills the file no longer
agrees with. Edit the CSV, rerun this; history lives in git.
"""

from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery

from shared import bigquery_client, dataset_name, replace_table, table_id

from reference import SKILLS_TAXONOMY_CSV
from reference.parsing.dim_skills import parse_skills_taxonomy, to_bigquery_rows

load_dotenv()

DIM_SKILLS_TABLE = "dim_skills"
DIM_SKILLS_SCHEMA = [
    bigquery.SchemaField("alias", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("canonical_skill", "STRING", mode="REQUIRED"),
]


def load_dim_skills(csv_path: Path = SKILLS_TAXONOMY_CSV) -> int:
    """Replaces `dim_skills` with the aliases in `csv_path`. Returns the row count."""
    aliases = parse_skills_taxonomy(csv_path.read_text(encoding="utf-8"))
    rows = to_bigquery_rows(aliases)

    client = bigquery_client()
    table = table_id(client, dataset_name("silver"), DIM_SKILLS_TABLE)
    replace_table(
        client,
        table,
        rows,
        DIM_SKILLS_SCHEMA,
    )

    canonical_count = len({entry.canonical_skill for entry in aliases})
    print(
        f"Loaded {len(rows)} aliases covering {canonical_count} canonical skills "
        f"into {table}"
    )
    return len(rows)


if __name__ == "__main__":
    load_dim_skills()
