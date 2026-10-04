"""
Parses and validates `location_aliases_review.csv` into
`dim_location_aliases` rows.

    location_token -> country

`location_token` is the last comma-separated part of a CV's location string.
It is usually a country (`United Kingdom`, `Sweden`), sometimes an alias of one
(`UK`, `Scotland` -> United Kingdom), and occasionally a city where the CV gave
no country at all (`Stockholm` -> Sweden). All three resolve through the same
lookup.
"""

from reference.parsing.common.reference_csv import ReferenceDataError, read_csv_rows

REQUIRED_COLUMNS = ["location_token", "country"]
KEY_COLUMN = "location_token"


def parse_location_aliases(csv_text: str) -> list[dict]:
    """
    The reviewed rows: {location_token, country}.

    Raises ReferenceDataError when a token has no country. A blank country is
    a half-finished review, and the column is REQUIRED in BigQuery, so the
    load would fail later and less clearly.
    """
    reviewed = read_csv_rows(
        csv_text,
        required_columns=REQUIRED_COLUMNS,
        key_column=KEY_COLUMN,
    )

    unmapped = [entry["location_token"] for entry in reviewed if not entry["country"]]
    if unmapped:
        raise ReferenceDataError(
            f"These location tokens have no country filled in: {unmapped}"
        )

    return reviewed


def to_bigquery_rows(reviewed: list[dict]) -> list[dict]:
    """Shapes reviewed rows as `dim_location_aliases` rows."""
    return [
        {"location_token": entry["location_token"], "country": entry["country"]}
        for entry in reviewed
    ]
