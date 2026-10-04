"""
Loads the reviewed location aliases into `silver.dim_location_aliases`.

Full refresh, for the same reason as the other dimensions: the CSV is the
single source of truth, so the table is replaced with exactly what it says.

Cities are parsed from the CV's location string rather than listed in the CSV,
so a CV mentioning a new city needs no change to the reviewed file — only a
new *country* does.
"""

from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery

from shared import bigquery_client, dataset_name, replace_table, table_id

from reference import LOCATION_ALIASES_CSV
from reference.parsing.dim_location_aliases import (
    parse_location_aliases,
    to_bigquery_rows,
)

load_dotenv()

DIM_LOCATION_ALIASES_TABLE = "dim_location_aliases"
DIM_LOCATION_ALIASES_SCHEMA = [
    bigquery.SchemaField("location_token", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("country", "STRING", mode="REQUIRED"),
]


def load_dim_location_aliases(csv_path: Path = LOCATION_ALIASES_CSV) -> int:
    """Replaces `dim_location_aliases` with the aliases in `csv_path`."""
    reviewed = parse_location_aliases(csv_path.read_text(encoding="utf-8"))
    rows = to_bigquery_rows(reviewed)

    client = bigquery_client()
    table = table_id(client, dataset_name("silver"), DIM_LOCATION_ALIASES_TABLE)
    replace_table(client, table, rows, DIM_LOCATION_ALIASES_SCHEMA)

    countries = len({row["country"] for row in rows})
    print(f"Loaded {len(rows)} location aliases covering {countries} countries into {table}")
    return len(rows)


if __name__ == "__main__":
    load_dim_location_aliases()
