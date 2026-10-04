"""
bronze.raw_candidates -> silver.silver_candidates, as pure functions.

Name to uppercase, phone to E.164, email validated against a pattern.
No I/O, so every rule is unit testable without mocking BigQuery.
"""

import re

import phonenumbers

_EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$"
)

# Default region used to interpret numbers with no country code (e.g. "20
# 7183 8750"). Most CVs in this dataset are UK-based; a number that already
# carries its own country code ("+1 415...") is parsed using that instead.
_DEFAULT_REGION = "GB"


def standardize_name(name: str) -> str:
    """Uppercases and collapses whitespace. Empty/missing names become ''."""
    if not name:
        return ""
    return re.sub(r"\s+", " ", name.strip()).upper()


def standardize_phone(phone: str) -> str | None:
    """
    Normalizes a phone number to E.164 format (e.g. `+34612458907`,
    `+14155552671`), for any country.

    Numbers that already carry a country code ("+1 415 555 2671", "0034 612
    458 907") are parsed using that code. Numbers with no country code
    ("020 7183 8750") are assumed to be in `_DEFAULT_REGION`. Returns None
    when the input can't be parsed into a valid, assignable number for its
    country (wrong length, bad prefix, etc).
    """
    if not phone:
        return None

    try:
        parsed = phonenumbers.parse(phone, _DEFAULT_REGION)
    except phonenumbers.NumberParseException:
        return None

    if not phonenumbers.is_valid_number(parsed):
        return None

    return phonenumbers.format_number(
        parsed, phonenumbers.PhoneNumberFormat.E164
    )


def is_valid_email(email: str) -> bool:
    """
    True when `email` contains "@", a domain, no spaces, and matches a
    standard email pattern.
    """
    if not email:
        return False
    if " " in email:
        return False
    if "@" not in email:
        return False

    local, _, domain = email.partition("@")
    if not domain or "." not in domain:
        return False

    return bool(_EMAIL_PATTERN.match(email))


def transform_candidate_row(row: dict) -> dict:
    """Applies standardization/validation to one raw_candidates row."""
    email = (row.get("email") or "").strip()
    phone = standardize_phone(row.get("phone") or "")

    return {
        "submission_id": row["submission_id"],
        "candidate_name": standardize_name(row.get("candidate_name") or ""),
        "email": email,
        "is_email_valid": is_valid_email(email),
        "phone": phone,
        "is_phone_valid": phone is not None,
        "linkedin": (row.get("linkedin") or "").strip(),
        "github": (row.get("github") or "").strip(),
    }


