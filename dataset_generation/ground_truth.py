"""
The ground truth file: what each generated CV is, and what was planted in it.

Written as each CV is made, so it records what was generated rather than
what the current code would generate. Without it the only record of a CV is
its filename, and reading that filename means re-running spec code that has
since changed - which is how an earlier dataset lost the link between a PDF
and the inconsistencies it carries.

It is also what makes per-type results possible: "28 of 32 date overlaps
were detected" needs this file, "71% of inconsistent CVs were detected"
does not.
"""

import csv
from pathlib import Path

FIELDS = [
    "id",
    "folder",
    "role",
    "seniority",
    "years",
    "location",
    "github",
    "inconsistency_types",
    "filename",
]

# inconsistency_types holds a list; a pipe keeps it in one CSV column without
# fighting the comma separator.
TYPE_SEPARATOR = "|"


def read_entries(path: Path) -> list[dict]:
    """Every CV recorded so far, oldest first. Empty when there is no file."""
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [
            {**row, "inconsistency_types": _split(row["inconsistency_types"])}
            for row in csv.DictReader(handle)
        ]


def recorded_ids(path: Path) -> set[str]:
    """The ids already generated, used to decide what is left to make."""
    return {entry["id"] for entry in read_entries(path)}


def append_entry(path: Path, *, spec: dict, filename: str) -> None:
    """Records one CV, writing the header first if the file is new."""
    is_new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(
            {
                "id": spec["id"],
                "folder": spec["folder"],
                "role": spec["role"],
                "seniority": spec["seniority"],
                "years": spec["years"],
                "location": spec["location"]["city"],
                "github": spec["github"],
                "inconsistency_types": TYPE_SEPARATOR.join(spec["inconsistency_types"]),
                "filename": filename,
            }
        )


def _split(value: str) -> list[str]:
    """The types column back as a list; an empty cell means none were planted."""
    return [part for part in value.split(TYPE_SEPARATOR) if part]
