"""
Tests for the dataset plan.

These are cheap because specs.py is pure: the plan for 600 CVs can be checked
without generating one, which is the point of separating it from the API call.
"""

from collections import Counter

import pytest

from dataset_generation.inconsistencies import INCONSISTENCY_TYPES
from dataset_generation.specs import (
    LOCATIONS,
    MAX_INCONSISTENCIES_PER_CV,
    MIN_INCONSISTENCIES_PER_CV,
    ROLES,
    SENIOR_ONLY_ROLES,
    SENIORITY_CONFIG,
    cv_filename,
    generate_specs,
)


def test_half_the_dataset_is_inconsistent_spec():
    specs = generate_specs(300)
    counts = Counter(spec["folder"] for spec in specs)
    assert counts == {"inconsistent": 150, "legitimate": 150}


def test_an_odd_total_puts_the_extra_cv_in_legitimate():
    """total // 2 is inconsistencyed, so 301 gives 150 inconsistencyed and 151 clean."""
    counts = Counter(spec["folder"] for spec in generate_specs(301))
    assert counts == {"legitimate": 151, "inconsistent": 150}


def test_ids_are_sequential_and_zero_padded():
    specs = generate_specs(12)
    assert [spec["id"] for spec in specs] == [
        "001", "002", "003", "004", "005", "006",
        "007", "008", "009", "010", "011", "012",
    ]


def test_the_plan_is_reproducible():
    """A fixed seed means the same plan, so a rerun resumes the same dataset."""
    assert generate_specs(50) == generate_specs(50)


def test_every_inconsistencyed_cv_gets_between_one_and_three_inconsistencies():
    for spec in generate_specs(300):
        if spec["folder"] == "inconsistent":
            count = len(spec["inconsistency_types"])
            assert MIN_INCONSISTENCIES_PER_CV <= count <= MAX_INCONSISTENCIES_PER_CV
        else:
            assert spec["inconsistency_types"] == []


def test_inconsistencies_are_never_repeated_within_one_cv():
    for spec in generate_specs(300):
        keys = spec["inconsistency_types"]
        assert len(keys) == len(set(keys))


def test_inconsistency_keys_and_their_prompts_stay_aligned():
    """
    `inconsistencies` holds the prompt text for `inconsistency_types`. If these
    drift apart, a CV is labelled with one inconsistency and asked for another.
    """
    for spec in generate_specs(300):
        assert len(spec["inconsistencies"]) == len(spec["inconsistency_types"])
        for key, text in zip(spec["inconsistency_types"], spec["inconsistencies"]):
            assert text == INCONSISTENCY_TYPES[key]


def test_every_inconsistency_type_appears_somewhere_in_a_300_cv_dataset():
    """A inconsistency that is never planted cannot be measured."""
    planted = {
        key for spec in generate_specs(300) for key in spec["inconsistency_types"]
    }
    assert planted == set(INCONSISTENCY_TYPES)


def test_senior_only_roles_are_never_junior_or_mid():
    """Nobody is a Junior Principal Engineer."""
    for spec in generate_specs(300):
        if spec["role"] in SENIOR_ONLY_ROLES:
            assert spec["seniority"] in {"Senior", "Staff"}


def test_years_always_match_the_declared_seniority():
    for spec in generate_specs(300):
        assert spec["years"] in SENIORITY_CONFIG[spec["seniority"]]["years"]


def test_roles_and_locations_come_from_the_configured_lists():
    for spec in generate_specs(300):
        assert spec["role"] in ROLES
        assert spec["location"] in LOCATIONS


def test_a_location_phone_prefix_belongs_to_its_country():
    """
    The geo_mismatch inconsistency works by contradicting this, so the baseline has to
    be consistent: every UK city carries +44 and no other country does.
    """
    for location in LOCATIONS:
        if location["country"] == "United Kingdom":
            assert location["phone"] == "+44"
        else:
            assert location["phone"] != "+44"


@pytest.mark.parametrize(
    "spec, expected",
    [
        ({"id": "001", "role": "Data Engineer", "seniority": "Senior"},
         "cv_001_data_engineer_senior.pdf"),
        ({"id": "150", "role": "Machine Learning Engineer", "seniority": "Staff"},
         "cv_150_machine_learning_engineer_staff.pdf"),
    ],
)
def test_cv_filename(spec, expected):
    assert cv_filename(spec) == expected


def test_filenames_are_unique_across_the_dataset():
    """Two specs sharing a filename would silently overwrite one another."""
    names = [cv_filename(spec) for spec in generate_specs(300)]
    assert len(names) == len(set(names))
