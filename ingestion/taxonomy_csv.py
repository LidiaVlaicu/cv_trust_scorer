"""
Pure parsing and validation of the reviewed skills-taxonomy CSV.

`skills_taxonomy_review.csv` is the single source of truth for the skills
taxonomy: one row per canonical skill, with every alias it can appear as on a
CV pipe-separated in the `aliases` column. It is reviewed by a human and
version-controlled, so changes are diffable and no classification logic lives
in code.

This module only turns that file's shape into flat (alias, canonical_skill)
pairs and checks the file's internal consistency. No file system access and no
BigQuery, so every function here is unit-testable on a plain string.

Note what this module deliberately does NOT do: it does not lowercase or
otherwise normalize aliases. Deriving the lookup key is the job of exactly one
function, `transformations.skill_lookup_key`, used at match time — keeping it
in one place means the loader and the matcher cannot drift apart.
"""

import csv
import io
from dataclasses import dataclass

CANONICAL_COLUMN = "canonical_skill"
ALIASES_COLUMN = "aliases"
ALIAS_COUNT_COLUMN = "alias_count"
ALIAS_SEPARATOR = "|"


class TaxonomyError(ValueError):
    """Raised when the taxonomy CSV is internally inconsistent."""


@dataclass(frozen=True)
class TaxonomyAlias:
    """One alias of one canonical skill — a single row of `dim_skills`."""

    alias: str
    canonical_skill: str


def parse_taxonomy_csv(csv_text: str) -> list[TaxonomyAlias]:
    """
    Explodes the reviewed CSV into one TaxonomyAlias per alias.

    Raises TaxonomyError if a required column is missing, a canonical skill is
    blank, a row has no aliases, or a row's `alias_count` disagrees with the
    aliases actually listed (that column is a self-check carried by the file,
    so a mismatch means the file was edited inconsistently).
    """
    reader = csv.DictReader(io.StringIO(csv_text))

    if reader.fieldnames is None:
        raise TaxonomyError("Taxonomy CSV is empty")

    missing_columns = {CANONICAL_COLUMN, ALIASES_COLUMN} - set(reader.fieldnames)
    if missing_columns:
        raise TaxonomyError(f"Taxonomy CSV is missing columns: {sorted(missing_columns)}")

    parsed: list[TaxonomyAlias] = []

    for line_number, row in enumerate(reader, start=2):  # line 1 is the header
        canonical = (row.get(CANONICAL_COLUMN) or "").strip()
        if not canonical:
            raise TaxonomyError(f"Line {line_number}: blank {CANONICAL_COLUMN}")

        aliases = [
            alias.strip()
            for alias in (row.get(ALIASES_COLUMN) or "").split(ALIAS_SEPARATOR)
            if alias.strip()
        ]
        if not aliases:
            raise TaxonomyError(f"Line {line_number}: '{canonical}' has no aliases")

        declared_count = (row.get(ALIAS_COUNT_COLUMN) or "").strip()
        if declared_count and int(declared_count) != len(aliases):
            raise TaxonomyError(
                f"Line {line_number}: '{canonical}' declares "
                f"{ALIAS_COUNT_COLUMN}={declared_count} but lists {len(aliases)} aliases"
            )

        parsed.extend(
            TaxonomyAlias(alias=alias, canonical_skill=canonical) for alias in aliases
        )

    if not parsed:
        raise TaxonomyError("Taxonomy CSV contains no aliases")

    _reject_repeated_aliases(parsed)
    return parsed


def _reject_repeated_aliases(aliases: list[TaxonomyAlias]) -> None:
    """
    Rejects the same alias string appearing under more than one canonical skill.

    Case-insensitive collisions that agree on the canonical skill are fine and
    expected ("Code Splitting" and "Code splitting" both map to "Code
    Splitting"); they are caught at match time by build_skills_taxonomy only
    when they *disagree*.
    """
    seen: dict[str, str] = {}
    for entry in aliases:
        previous = seen.get(entry.alias)
        if previous is not None and previous != entry.canonical_skill:
            raise TaxonomyError(
                f"Alias '{entry.alias}' is claimed by both "
                f"'{previous}' and '{entry.canonical_skill}'"
            )
        seen[entry.alias] = entry.canonical_skill


def to_bigquery_rows(aliases: list[TaxonomyAlias]) -> list[dict]:
    """Shapes parsed aliases as `dim_skills` rows."""
    return [
        {"alias": entry.alias, "canonical_skill": entry.canonical_skill}
        for entry in aliases
    ]
