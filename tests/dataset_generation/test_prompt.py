"""
Tests for the generated prompt.

The prompt is the only place the dataset is actually specified, and it used to
be unreachable without an API call. These assert what the model is asked for -
including that it is never asked for two contradictory things.
"""

from dataset_generation.inconsistencies import INCONSISTENCY_TYPES
from dataset_generation.prompt import HUMAN_SUMMARY, build_cv_prompt
from dataset_generation.specs import generate_specs


def spec(**overrides) -> dict:
    base = {
        "id": "001",
        "folder": "legitimate",
        "role": "Data Engineer",
        "seniority": "Senior",
        "years": "7",
        "location": {"city": "Bristol", "country": "United Kingdom", "phone": "+44"},
        "github": True,
        "inconsistency_types": [],
        "inconsistencies": [],
    }
    return {**base, **overrides}


def inconsistent_spec(*keys) -> dict:
    return spec(
        folder="inconsistent",
        inconsistency_types=list(keys),
        inconsistencies=[INCONSISTENCY_TYPES[key] for key in keys],
    )


# ── the spec reaches the prompt ───────────────────────────────────────────
def test_the_prompt_states_the_role_seniority_years_and_place():
    prompt = build_cv_prompt(spec())
    assert "Role: Data Engineer" in prompt
    assert "Seniority: Senior" in prompt
    assert "Years of experience: 7" in prompt
    assert "City: Bristol, United Kingdom" in prompt
    assert "starting with +44" in prompt
    assert "Education from a real university in United Kingdom" in prompt


def test_github_is_asked_for_or_refused():
    assert "GitHub URL with 3-4 relevant public repositories" in build_cv_prompt(
        spec(github=True))
    assert "No GitHub URL" in build_cv_prompt(spec(github=False))


# ── inconsistencies ──────────────────────────────────────────────────────
def test_a_clean_cv_is_given_no_inconsistency_instructions():
    prompt = build_cv_prompt(spec())
    assert "INCONSISTENCIES TO INCLUDE" not in prompt
    assert HUMAN_SUMMARY in prompt


def test_inconsistencies_are_listed_and_numbered():
    prompt = build_cv_prompt(inconsistent_spec("date_overlap", "geo_mismatch"))
    assert "INCONSISTENCIES TO INCLUDE (follow exactly):" in prompt
    assert "1. " + INCONSISTENCY_TYPES["date_overlap"] in prompt
    assert "2. " + INCONSISTENCY_TYPES["geo_mismatch"] in prompt


def test_the_ai_text_inconsistency_suppresses_the_human_voice_instruction():
    """
    The regression this file exists for.

    Before the split, the check searched for the string "ai_text" inside the
    inconsistency PROSE, where it never appears - so the model was told to
    write buzzword-heavy AI prose AND to write in a natural human voice, in
    one prompt. Asking for both means it may not be planted at all.
    """
    prompt = build_cv_prompt(inconsistent_spec("ai_text"))
    assert "AI-generated language" in prompt       # the inconsistency is asked for
    assert HUMAN_SUMMARY not in prompt             # and not contradicted
    assert "natural human voice" not in prompt


def test_other_inconsistencies_still_ask_for_a_human_voice():
    """Only ai_text suppresses it; a date overlap says nothing about tone."""
    prompt = build_cv_prompt(inconsistent_spec("date_overlap"))
    assert HUMAN_SUMMARY in prompt


def test_ai_text_is_suppressed_even_when_combined_with_other_inconsistencies():
    prompt = build_cv_prompt(
        inconsistent_spec("fictional_company", "ai_text", "date_overlap")
    )
    assert HUMAN_SUMMARY not in prompt
    assert "AI-generated language" in prompt
    assert INCONSISTENCY_TYPES["fictional_company"] in prompt


# ── output format ─────────────────────────────────────────────────────────
def test_the_prompt_forbids_markdown():
    prompt = build_cv_prompt(spec())
    assert "Plain text only" in prompt
    assert "No markdown" in prompt


def test_every_spec_in_the_dataset_builds_a_prompt():
    """No spec combination can crash prompt building."""
    for candidate in generate_specs(300):
        prompt = build_cv_prompt(candidate)
        assert candidate["role"] in prompt
        assert candidate["location"]["city"] in prompt
