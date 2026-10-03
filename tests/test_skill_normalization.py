"""
Tests for the pure skill clean -> standardize -> normalize -> validate chain.

The taxonomy is injected, so none of this needs BigQuery.
"""

import pytest

from orchestration.assets.transformations import (
    build_skills_taxonomy,
    clean_skill,
    normalize_skill,
    skill_lookup_key,
    transform_skill_row,
)

# Shaped exactly like the `dim_skills` rows the warehouse returns.
_DIM_SKILLS_ROWS = [
    {"alias": "Power BI", "canonical_skill": "Power BI"},
    {"alias": "PowerBI", "canonical_skill": "Power BI"},
    {"alias": "Microsoft Power BI", "canonical_skill": "Power BI"},
    {"alias": "Looker", "canonical_skill": "Looker"},
    {"alias": "Google Looker", "canonical_skill": "Looker"},
    {"alias": "Looker Studio", "canonical_skill": "Looker Studio"},
    {"alias": "Google Data Studio", "canonical_skill": "Looker Studio"},
    {"alias": "Snowflake", "canonical_skill": "Snowflake"},
    {"alias": "Snowflake schema", "canonical_skill": "Snowflake Schema"},
]

TAXONOMY = build_skills_taxonomy(_DIM_SKILLS_ROWS)


def test_clean_skill_trims_collapses_and_normalizes_unicode():
    assert clean_skill("  Power   BI  ") == "Power BI"
    assert clean_skill("Power\tBI\n") == "Power BI"
    assert clean_skill("ＰowerBI") == "PowerBI"  # full-width char normalized by NFKC
    assert clean_skill("") == ""


def test_skill_lookup_key_is_cleaned_and_lowercased():
    assert skill_lookup_key("  Power   BI ") == "power bi"
    assert skill_lookup_key("POWERBI") == "powerbi"
    assert skill_lookup_key("") == ""


def test_normalize_skill_merges_synonyms():
    assert normalize_skill("Power BI", TAXONOMY) == "Power BI"
    assert normalize_skill("powerbi", TAXONOMY) == "Power BI"
    assert normalize_skill("  MICROSOFT   power bi ", TAXONOMY) == "Power BI"


def test_normalize_skill_keeps_distinct_products_apart():
    """The distinctions validated by hand in the CSV must survive."""
    assert normalize_skill("Looker", TAXONOMY) == "Looker"
    assert normalize_skill("Google Looker", TAXONOMY) == "Looker"
    assert normalize_skill("Google Data Studio", TAXONOMY) == "Looker Studio"
    assert normalize_skill("Snowflake", TAXONOMY) == "Snowflake"
    assert normalize_skill("Snowflake schema", TAXONOMY) == "Snowflake Schema"


def test_normalize_skill_returns_none_when_not_in_taxonomy():
    assert normalize_skill("PowerBII", TAXONOMY) is None
    assert normalize_skill("", TAXONOMY) is None


def test_build_skills_taxonomy_rejects_conflicting_aliases():
    """A broken taxonomy must fail loudly, not resolve to whichever row won."""
    with pytest.raises(ValueError, match="Conflicting taxonomy"):
        build_skills_taxonomy(
            [
                {"alias": "Power BI", "canonical_skill": "Power BI"},
                {"alias": "power bi", "canonical_skill": "Microsoft Power BI"},
            ]
        )


def test_build_skills_taxonomy_allows_case_variants_that_agree():
    taxonomy = build_skills_taxonomy(
        [
            {"alias": "Code Splitting", "canonical_skill": "Code Splitting"},
            {"alias": "code splitting", "canonical_skill": "Code Splitting"},
        ]
    )
    assert taxonomy.alias_count == 1
    assert normalize_skill("CODE SPLITTING", taxonomy) == "Code Splitting"


def test_transform_skill_row_cleans_internally_and_keeps_the_raw_value():
    """Cleaning happens inside the transform; only raw + canonical are kept."""
    row = {
        "skill_id": "cv_001_power_bi",
        "submission_id": "cv_001",
        "skill_name": "  POWER   bi ",
    }

    assert transform_skill_row(row, TAXONOMY) == {
        "skill_id": "cv_001_power_bi",
        "submission_id": "cv_001",
        "raw_skill": "  POWER   bi ",
        "normalized_skill": "Power BI",
    }


def test_transform_skill_row_flags_unmatched_without_dropping_it():
    row = {
        "skill_id": "cv_002_powerbii",
        "submission_id": "cv_002",
        "skill_name": "PowerBII",
    }

    result = transform_skill_row(row, TAXONOMY)

    assert result["raw_skill"] == "PowerBII"
    assert result["normalized_skill"] is None
