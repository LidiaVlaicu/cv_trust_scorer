"""
The Claude call.

Isolated so that everything deciding WHAT to ask for (specs, inconsistencies,
prompt) stays pure and testable, and only this file costs money to exercise.
"""

import os

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 1500

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """
    The API client, created on first use.

    Lazy rather than created at import time so that importing this module -
    which a test collector does - does not require an API key to be set.
    """
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


def generate_cv_text(prompt: str) -> str:
    """Sends `prompt` to Claude and returns the CV text it produced."""
    message = _get_client().messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text
