"""
Loads the reviewed location aliases into the `dim_location_aliases` table.

    location_aliases_review.csv  (reviewed, version-controlled)
                |
                v  parse + validate (pure, see reference_csv.py)
      silver.dim_location_aliases   (location_token -> country)

`location_token` is the last comma-separated part of a CV's location string.
It is usually a country (`United Kingdom`, `Sweden`), sometimes an alias of one
(`UK`, `Scotland`, `Northern Ireland` -> United Kingdom), and occasionally a
city where the CV gave no country at all (`Stockholm` -> Sweden). All three
cases resolve through the same lookup.

Cities are parsed from the string rather than listed here, so a CV mentioning a
new city needs no change to this file — only a new *country* does.

Run with:  python -m reference.loaders.dim_location_aliases
"""

from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery

from warehouse import bigquery_client, dataset_name, replace_table, table_id

from reference import LOCATION_ALIASES_CSV
from reference.parsing.reference_csv import ReferenceDataError, parse_reference_csv

load_dotenv()

LOCATION_ALIASES_CSV_PATH = LOCATION_ALIASES_CSV

DIM_LOCATION_ALIASES_TABLE = "dim_location_aliases"
DIM_LOCATION_ALIASES_SCHEMA = [
    bigquery.SchemaField("location_token", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("country", "STRING", mode="REQUIRED"),
]


def load_dim_location_aliases(csv_path: Path = LOCATION_ALIASES_CSV_PATH) -> int:
    """Replaces `dim_location_aliases` with the aliases in `csv_path`."""
    reviewed = parse_reference_csv(
        csv_path.read_text(encoding="utf-8"),
        required_columns=["location_token", "country"],
        key_column="location_token",
    )

    unmapped = [entry["location_token"] for entry in reviewed if not entry["country"]]
    if unmapped:
        raise ReferenceDataError(
            f"These location tokens have no country filled in: {unmapped}"
        )

    rows = [
        {"location_token": entry["location_token"], "country": entry["country"]}
        for entry in reviewed
    ]

    client = bigquery_client()
    table = table_id(client, dataset_name("silver"), DIM_LOCATION_ALIASES_TABLE)
    replace_table(client, table, rows, DIM_LOCATION_ALIASES_SCHEMA)

    countries = len({row["country"] for row in rows})
    print(f"Loaded {len(rows)} location aliases covering {countries} countries into {table}")
    return len(rows)


if __name__ == "__main__":
    load_dim_location_aliases()
