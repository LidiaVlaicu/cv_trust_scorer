"""
Tests for the location aliases dimension, including golden checks against the
real review file so an accidental edit to it fails loudly.
"""

import pytest

from reference import LOCATION_ALIASES_CSV
from reference.parsing.dim_location_aliases import (
    parse_location_aliases,
    to_bigquery_rows,
)
from reference.parsing.common.reference_csv import ReferenceDataError
from silver.rules.work_experience import build_work_experience_reference


def _reviewed() -> list[dict]:
    return parse_location_aliases(LOCATION_ALIASES_CSV.read_text(encoding="utf-8"))


def _reference():
    return build_work_experience_reference([], _reviewed())


# ── parsing and validation ────────────────────────────────────────────────
def test_a_token_with_no_country_is_rejected():
    text = "location_token,country\nUK,United Kingdom\nAtlantis,\n"

    with pytest.raises(ReferenceDataError, match="no country filled in"):
        parse_location_aliases(text)


def test_rows_are_shaped_for_bigquery():
    text = "location_token,country,notes\n UK , United Kingdom ,whatever\n"

    assert to_bigquery_rows(parse_location_aliases(text)) == [
        {"location_token": "UK", "country": "United Kingdom"}
    ]


# ── golden checks on the real review file ─────────────────────────────────
def test_the_real_file_parses_and_every_alias_has_a_country():
    aliases = _reviewed()

    assert len(aliases) == 15
    assert [a["location_token"] for a in aliases if not a["country"]] == []
    assert len(_reference().country_by_location_token) == 15


@pytest.mark.parametrize(
    "location_token, expected_country",
    [
        ("United Kingdom", "United Kingdom"),
        ("UK", "United Kingdom"),
        ("Scotland", "United Kingdom"),
        ("Northern Ireland", "United Kingdom"),
        ("Ireland", "Ireland"),
        ("Stockholm", "Sweden"),
        ("Västerås", "Sweden"),
    ],
)
def test_reviewed_country_golden_examples(location_token, expected_country):
    assert _reference().country_for(location_token) == expected_country
