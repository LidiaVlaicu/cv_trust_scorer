"""
Tests for parsing/validating the reviewed taxonomy CSV, plus golden-example
checks against the real file.

The golden examples guard the merge decisions that were validated by hand —
if someone later edits the CSV and accidentally collapses Looker into Looker
Studio, these fail.
"""

from pathlib import Path

import pytest

from reference import SKILLS_TAXONOMY_CSV as TAXONOMY_CSV
from reference.parsing.taxonomy_csv import (
    TaxonomyError,
    parse_taxonomy_csv,
    to_bigquery_rows,
)
from orchestration.assets.transformations import build_skills_taxonomy, normalize_skill

_VALID_CSV = """canonical_skill,alias_count,aliases,notes
Power BI,2,Power BI|PowerBI,
Looker,1,Looker,some note
"""


def test_parse_explodes_pipe_separated_aliases():
    aliases = parse_taxonomy_csv(_VALID_CSV)

    assert [(a.alias, a.canonical_skill) for a in aliases] == [
        ("Power BI", "Power BI"),
        ("PowerBI", "Power BI"),
        ("Looker", "Looker"),
    ]


def test_to_bigquery_rows_shapes_dim_skills_rows():
    rows = to_bigquery_rows(parse_taxonomy_csv(_VALID_CSV))

    assert rows[0] == {"alias": "Power BI", "canonical_skill": "Power BI"}
    assert all(set(row) == {"alias", "canonical_skill"} for row in rows)


def test_parse_rejects_alias_count_that_disagrees_with_the_aliases():
    csv_text = "canonical_skill,alias_count,aliases\nPower BI,5,Power BI|PowerBI\n"
    with pytest.raises(TaxonomyError, match="alias_count=5 but lists 2"):
        parse_taxonomy_csv(csv_text)


def test_parse_rejects_blank_canonical_skill():
    with pytest.raises(TaxonomyError, match="blank canonical_skill"):
        parse_taxonomy_csv("canonical_skill,aliases\n,Power BI\n")


def test_parse_rejects_row_without_aliases():
    with pytest.raises(TaxonomyError, match="has no aliases"):
        parse_taxonomy_csv("canonical_skill,aliases\nPower BI,\n")


def test_parse_rejects_alias_claimed_by_two_canonicals():
    csv_text = (
        "canonical_skill,aliases\n"
        "Power BI,Power BI|Dashboards\n"
        "Tableau,Dashboards\n"
    )
    with pytest.raises(TaxonomyError, match="claimed by both"):
        parse_taxonomy_csv(csv_text)


def test_parse_rejects_missing_columns():
    with pytest.raises(TaxonomyError, match="missing columns"):
        parse_taxonomy_csv("skill,synonyms\nPower BI,PowerBI\n")


# ── Golden examples against the real reviewed CSV ─────────────────────────
def test_real_csv_parses_and_builds_a_conflict_free_taxonomy():
    aliases = parse_taxonomy_csv(TAXONOMY_CSV.read_text(encoding="utf-8"))
    taxonomy = build_skills_taxonomy(to_bigquery_rows(aliases))

    assert len(aliases) == 887
    assert len({a.canonical_skill for a in aliases}) == 605
    # 887 aliases collapse to 741 distinct lookup keys (case-variant pairs)
    assert taxonomy.alias_count == 741


@pytest.mark.parametrize(
    "raw_skill, expected",
    [
        # synonym merges
        ("  Power   BI ", "Power BI"),
        ("PowerBI", "Power BI"),
        ("Excel", "Microsoft Excel"),
        ("Scikit-Learn", "scikit-learn"),
        ("Database Optimisation", "Database Optimization"),
        ("ETL pipeline development", "ETL"),
        ("JIRA", "Jira"),
        ("Jupyter notebooks", "Jupyter Notebook"),
        # renamed product
        ("Google Data Studio", "Looker Studio"),
        # distinctions that must NOT be merged
        ("Looker", "Looker"),
        ("Snowflake", "Snowflake"),
        ("Snowflake schema", "Snowflake Schema"),
        ("Angular", "Angular"),
        ("AngularJS", "AngularJS"),
        ("unittest", "unittest"),
        ("Unit Testing", "Unit Testing"),
        ("Transformers", "Hugging Face Transformers"),
        ("Transformer models", "Transformer Models"),
        # not in the taxonomy at all
        ("PowerBII", None),
        ("Some Tool Invented Tomorrow", None),
    ],
)
def test_real_csv_golden_examples(raw_skill, expected):
    taxonomy = build_skills_taxonomy(
        to_bigquery_rows(parse_taxonomy_csv(TAXONOMY_CSV.read_text(encoding="utf-8")))
    )
    assert normalize_skill(raw_skill, taxonomy) == expected
