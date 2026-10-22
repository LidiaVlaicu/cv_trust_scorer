"""
Tests for the contract Claude's extraction must satisfy.

The models are the only thing standing between a free-form LLM response and
the warehouse, so the cases here are the ones a model actually produces:
placeholders instead of an answer, missing fields, over-long values, and
whitespace nobody asked for.
"""

import pytest
from pydantic import ValidationError

from bronze.schemas import ExtractedCV, WorkExperienceItem

JOB = {"job_title": "Data Engineer", "company_name": "ACME Ltd"}


def cv(**overrides) -> dict:
    return {"candidate_name": "Ada Lovelace", **overrides}


# ── ExtractedCV ───────────────────────────────────────────────────────────
def test_a_name_is_the_only_thing_required():
    parsed = ExtractedCV(**cv())

    assert parsed.work_experience == []
    assert parsed.skills == []
    assert parsed.email == ""


def test_a_missing_name_is_rejected():
    with pytest.raises(ValidationError):
        ExtractedCV()


def test_an_empty_name_is_rejected():
    with pytest.raises(ValidationError):
        ExtractedCV(**cv(candidate_name=""))


@pytest.mark.parametrize("placeholder", ["n/a", "none", "unknown", "candidate", "name"])
def test_a_placeholder_name_is_rejected(placeholder):
    with pytest.raises(ValidationError, match="placeholder"):
        ExtractedCV(**cv(candidate_name=placeholder))


def test_placeholder_detection_ignores_case_and_padding():
    with pytest.raises(ValidationError, match="placeholder"):
        ExtractedCV(**cv(candidate_name="  UNKNOWN  "))


def test_a_name_that_merely_contains_a_placeholder_word_is_kept():
    """ "Unknown" is a placeholder; "Unknown Soldier" is a name."""
    assert ExtractedCV(**cv(candidate_name="Unknown Soldier")).candidate_name == (
        "Unknown Soldier"
    )


def test_surrounding_whitespace_is_stripped_from_every_string():
    parsed = ExtractedCV(**cv(candidate_name="  Ada  ", email="  a@b.com  "))

    assert parsed.candidate_name == "Ada"
    assert parsed.email == "a@b.com"


def test_a_name_over_the_length_limit_is_rejected():
    with pytest.raises(ValidationError):
        ExtractedCV(**cv(candidate_name="a" * 201))


def test_more_skills_than_any_cv_has_is_rejected():
    with pytest.raises(ValidationError):
        ExtractedCV(**cv(skills=[f"skill{n}" for n in range(201)]))


def test_blank_skills_are_dropped():
    assert ExtractedCV(**cv(skills=["Python", "", "   "])).skills == ["Python"]


def test_skills_are_deduplicated_case_insensitively_keeping_the_first():
    parsed = ExtractedCV(**cv(skills=["Python", "PYTHON", "python", "SQL"]))

    assert parsed.skills == ["Python", "SQL"]


def test_work_experience_is_validated_as_well():
    with pytest.raises(ValidationError):
        ExtractedCV(**cv(work_experience=[{"job_title": "Engineer"}]))


# ── WorkExperienceItem ────────────────────────────────────────────────────
def test_a_job_needs_a_title_and_a_company():
    item = WorkExperienceItem(**JOB)

    assert item.job_title == "Data Engineer"
    assert item.company_name == "ACME Ltd"


@pytest.mark.parametrize("field", ["job_title", "company_name"])
def test_a_job_missing_either_is_rejected(field):
    with pytest.raises(ValidationError):
        WorkExperienceItem(**{k: v for k, v in JOB.items() if k != field})


@pytest.mark.parametrize("field", ["job_title", "company_name"])
@pytest.mark.parametrize("placeholder", ["n/a", "unknown", "tbd", "xxx"])
def test_a_placeholder_job_field_is_rejected(field, placeholder):
    with pytest.raises(ValidationError, match="placeholder"):
        WorkExperienceItem(**{**JOB, field: placeholder})


def test_a_job_still_in_progress_defaults_to_present():
    assert WorkExperienceItem(**JOB).end_date == "Present"


def test_dates_are_kept_as_the_cv_wrote_them():
    """Parsing happens in silver, so bronze stores the string verbatim."""
    item = WorkExperienceItem(**JOB, start_date="January 2020", end_date="Jan 2021")

    assert item.start_date == "January 2020"
    assert item.end_date == "Jan 2021"


def test_a_description_over_the_limit_is_rejected():
    with pytest.raises(ValidationError):
        WorkExperienceItem(**JOB, description="x" * 10001)


def test_is_current_defaults_to_false():
    assert WorkExperienceItem(**JOB).is_current is False
