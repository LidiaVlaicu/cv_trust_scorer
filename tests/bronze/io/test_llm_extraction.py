"""
Tests for the step between Claude's reply and the ExtractedCV contract.

No network: the parsing is separate from the API call, so the responses
that actually cause trouble - fenced JSON, placeholders, malformed text -
can be handed to it directly.
"""

import pytest
from pydantic import ValidationError

from bronze.io import llm_extraction as extraction
from bronze.io.llm_extraction import parse_extraction_response

VALID = '{"candidate_name": "Ada Lovelace", "work_experience": [], "skills": []}'


def test_plain_json_validates():
    assert parse_extraction_response(VALID).candidate_name == "Ada Lovelace"


def test_a_json_code_fence_is_stripped():
    assert parse_extraction_response(f"```json\n{VALID}\n```").candidate_name == (
        "Ada Lovelace"
    )


def test_a_bare_code_fence_is_stripped():
    assert parse_extraction_response(f"```\n{VALID}\n```").candidate_name == (
        "Ada Lovelace"
    )


def test_surrounding_whitespace_is_ignored():
    assert parse_extraction_response(f"\n\n  {VALID}  \n").candidate_name == (
        "Ada Lovelace"
    )


def test_a_placeholder_name_is_rejected():
    """The model answers rather than failing, so placeholders are caught here."""
    with pytest.raises(ValidationError, match="placeholder"):
        parse_extraction_response(
            '{"candidate_name": "unknown", "work_experience": [], "skills": []}'
        )


def test_a_missing_required_field_is_rejected():
    with pytest.raises(ValidationError):
        parse_extraction_response('{"work_experience": [], "skills": []}')


def test_text_that_is_not_json_is_rejected():
    with pytest.raises(ValidationError):
        parse_extraction_response("I could not read that CV.")


def test_skills_are_deduplicated_on_the_way_in():
    parsed = parse_extraction_response(
        '{"candidate_name": "Ada", "work_experience": [],'
        ' "skills": ["Python", "python", "", "SQL"]}'
    )

    assert parsed.skills == ["Python", "SQL"]


# ── the call itself ───────────────────────────────────────────────────────
class FakeMessages:
    def __init__(self, reply):
        self.calls = []
        self._reply = reply

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type("M", (), {"content": [type("B", (), {"text": self._reply})()]})()


@pytest.fixture
def claude(monkeypatch):
    """Replaces the SDK so no request is made and nothing is charged."""

    def install(reply=VALID):
        messages = FakeMessages(reply)
        monkeypatch.setattr(
            extraction.anthropic,
            "Anthropic",
            lambda api_key=None: type("C", (), {"messages": messages})(),
        )
        return messages

    return install


def test_the_cv_text_reaches_the_prompt(claude):
    messages = claude()

    extraction.extract_cv_data_with_claude("ADA LOVELACE\nData Engineer")

    (call,) = messages.calls
    assert "ADA LOVELACE" in call["messages"][0]["content"]


def test_the_reply_is_validated_before_it_is_returned(claude):
    claude()

    assert extraction.extract_cv_data_with_claude("some cv").candidate_name == (
        "Ada Lovelace"
    )


def test_a_fenced_reply_from_the_api_is_still_validated(claude):
    claude(reply=f"```json\n{VALID}\n```")

    assert extraction.extract_cv_data_with_claude("some cv").candidate_name == (
        "Ada Lovelace"
    )


def test_a_reply_that_fails_the_contract_raises(claude):
    claude(reply='{"candidate_name": "unknown"}')

    with pytest.raises(ValidationError):
        extraction.extract_cv_data_with_claude("some cv")
