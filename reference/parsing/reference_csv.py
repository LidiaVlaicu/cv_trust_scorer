"""
Pure parsing and validation of the reviewed reference CSVs.

Each reference CSV is a human-reviewed, version-controlled file that becomes a
`dim_*` table in BigQuery. This module only turns a CSV into rows and checks
the file's internal consistency — no file system access and no BigQuery, so it
is unit-testable on a plain string.

Used by the load_dim_* scripts in this package.
"""

import csv
import io


class ReferenceDataError(ValueError):
    """Raised when a reviewed reference CSV is internally inconsistent."""


def parse_reference_csv(
    csv_text: str,
    *,
    required_columns: list[str],
    key_column: str,
) -> list[dict]:
    """
    Reads `csv_text` and returns one dict per row, limited to
    `required_columns` and with every value stripped.

    Raises ReferenceDataError when a required column is missing, a row's key is
    blank, the same key appears twice, or the file has no rows. Failing loudly
    here is deliberate: a duplicated key in reviewed data would otherwise
    resolve to whichever row happened to be read last.
    """
    reader = csv.DictReader(io.StringIO(csv_text))

    if reader.fieldnames is None:
        raise ReferenceDataError("Reference CSV is empty")

    missing = set(required_columns) - set(reader.fieldnames)
    if missing:
        raise ReferenceDataError(f"Reference CSV is missing columns: {sorted(missing)}")

    rows: list[dict] = []
    first_seen_at: dict[str, int] = {}

    for line_number, raw_row in enumerate(reader, start=2):  # line 1 is the header
        key = (raw_row.get(key_column) or "").strip()
        if not key:
            raise ReferenceDataError(f"Line {line_number}: blank {key_column}")
        if key in first_seen_at:
            raise ReferenceDataError(
                f"Line {line_number}: duplicate {key_column} {key!r} "
                f"(already on line {first_seen_at[key]})"
            )
        first_seen_at[key] = line_number
        rows.append({column: (raw_row.get(column) or "").strip() for column in required_columns})

    if not rows:
        raise ReferenceDataError("Reference CSV contains no rows")

    return rows
