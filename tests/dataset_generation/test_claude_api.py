"""
Tests for the Claude call used to build the dataset.

Nothing here reaches the API. The client is replaced before every test, and
a leaked real call would cost money per CV, so the fixture resets the cached
client rather than trusting test order.
"""

import pytest

from dataset_generation import claude_api


class FakeMessages:
    def __init__(self, text="CV TEXT"):
        self.calls = []
        self._text = text

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type("M", (), {"content": [type("B", (), {"text": self._text})()]})()


class FakeAnthropic:
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.messages = FakeMessages()


@pytest.fixture(autouse=True)
def fake_client(monkeypatch):
    """Replaces the SDK and clears the cached client around every test."""
    monkeypatch.setattr(claude_api.anthropic, "Anthropic", FakeAnthropic)
    monkeypatch.setattr(claude_api, "_client", None)
    yield
    monkeypatch.setattr(claude_api, "_client", None)


def test_the_prompt_is_sent_and_the_text_comes_back():
    assert claude_api.generate_cv_text("write a CV") == "CV TEXT"


def test_the_prompt_is_sent_as_the_user_message():
    claude_api.generate_cv_text("write a CV")

    (call,) = claude_api._get_client().messages.calls
    assert call["messages"] == [{"role": "user", "content": "write a CV"}]


def test_the_configured_model_and_limit_are_used():
    claude_api.generate_cv_text("write a CV")

    (call,) = claude_api._get_client().messages.calls
    assert call["model"] == claude_api.MODEL
    assert call["max_tokens"] == claude_api.MAX_TOKENS


def test_the_client_is_created_once_and_reused():
    """Created lazily so importing this module needs no API key."""
    assert claude_api._get_client() is claude_api._get_client()


def test_importing_the_module_creates_no_client():
    assert claude_api._client is None


def test_the_api_key_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-key")
    monkeypatch.setattr(claude_api, "_client", None)

    assert claude_api._get_client().api_key == "a-key"
