"""
bronze.raw_skills -> silver.silver_skills, as pure functions.

clean -> standardize -> normalize -> validate, where normalizing means
matching against the reviewed taxonomy in `dim_skills`. There is no
guessing and no keyword heuristic: a skill either matches a reviewed alias
or it is reported as unmatched for a human to add to the CSV.

Anything that depends on a controlled vocabulary is a lookup against a
`dim_*` reference table loaded from a reviewed CSV, never a vocabulary
hardcoded here: callers fetch the rows, build the lookup object and inject
it. That keeps this module I/O-free while letting the vocabularies evolve
as reviewed data.
"""

import re
import unicodedata
from dataclasses import dataclass

def clean_skill(raw_skill: str) -> str:
    """
    CLEANING. Removes noise without changing meaning: normalizes Unicode
    (full-width and lookalike characters) to canonical form, strips
    leading/trailing whitespace, and collapses internal whitespace.

    "  Power   BI " -> "Power BI"
    """
    if not raw_skill:
        return ""
    normalized = unicodedata.normalize("NFKC", raw_skill)
    return re.sub(r"\s+", " ", normalized.strip())


def skill_lookup_key(raw_skill: str) -> str:
    """
    STANDARDIZATION. Puts a skill into the one consistent format used for
    taxonomy lookups: cleaned, then lowercased.

    "  Power   BI " and "POWERBI" -> "power bi" and "powerbi"

    This is the single definition of the lookup key. Both the taxonomy
    (alias side) and the bronze data (raw_skill side) are keyed through this
    function, so the two sides can never drift apart.
    """
    return clean_skill(raw_skill).lower()


@dataclass(frozen=True)
class SkillsTaxonomy:
    """
    Immutable in-memory lookup of skill alias -> canonical skill, built from
    the `dim_skills` reference table. Injected into the functions below so
    they stay pure and testable without BigQuery.
    """

    canonical_by_key: dict[str, str]

    def canonical_for(self, lookup_key: str) -> str | None:
        return self.canonical_by_key.get(lookup_key)

    @property
    def alias_count(self) -> int:
        return len(self.canonical_by_key)

    @property
    def canonical_skills(self) -> set[str]:
        return set(self.canonical_by_key.values())


def build_skills_taxonomy(dim_skills_rows: list[dict]) -> SkillsTaxonomy:
    """
    Builds the lookup from `dim_skills` rows (`{alias, canonical_skill}`).

    Raises ValueError if two aliases collapse to the same lookup key but
    disagree on the canonical skill — that is a broken taxonomy, and failing
    loudly here beats silently resolving a skill to whichever row happened to
    be read last.
    """
    canonical_by_key: dict[str, str] = {}

    for row in dim_skills_rows:
        key = skill_lookup_key(row["alias"])
        if not key:
            continue

        canonical = row["canonical_skill"]
        existing = canonical_by_key.get(key)
        if existing is not None and existing != canonical:
            raise ValueError(
                f"Conflicting taxonomy: lookup key '{key}' maps to both "
                f"'{existing}' and '{canonical}'"
            )
        canonical_by_key[key] = canonical

    return SkillsTaxonomy(canonical_by_key=canonical_by_key)


def normalize_skill(raw_skill: str, taxonomy: SkillsTaxonomy) -> str | None:
    """
    NORMALIZATION. Maps a skill to its canonical name, merging synonyms
    ("Google Data Studio" and "Looker Studio" both -> "Looker Studio").
    Returns None when the skill is not in the taxonomy.
    """
    return taxonomy.canonical_for(skill_lookup_key(raw_skill))


def transform_skill_row(row: dict, taxonomy: SkillsTaxonomy) -> dict:
    """
    Applies all four steps to one `raw_skills` row.

    Cleaning and standardization happen inside this function; only their end
    result is kept. `raw_skill` is preserved for traceability, and the
    intermediate values can always be re-derived from it with clean_skill()
    and skill_lookup_key().

    VALIDATION is expressed as `normalized_skill` being None: a skill that is
    not in the taxonomy is kept rather than dropped, so it can be reviewed and
    added, but it carries no canonical value.
    """
    raw_skill = row.get("skill_name") or ""

    return {
        "skill_id": row["skill_id"],
        "submission_id": row["submission_id"],
        "raw_skill": raw_skill,
        "normalized_skill": taxonomy.canonical_for(skill_lookup_key(raw_skill)),
    }


