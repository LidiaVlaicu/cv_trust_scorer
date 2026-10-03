from orchestration.assets.transformations import (
    is_valid_email,
    standardize_name,
    standardize_phone,
    transform_candidate_row,
)


def test_standardize_name_uppercases_and_collapses_whitespace():
    assert standardize_name("  Jane   Doe ") == "JANE DOE"
    assert standardize_name("maria garcía") == "MARIA GARCÍA"
    assert standardize_name("") == ""


def test_standardize_phone_accepts_bare_uk_numbers_via_default_region():
    assert standardize_phone("020 7183 8750") == "+442071838750"
    assert standardize_phone("07911-123456") == "+447911123456"


def test_standardize_phone_accepts_country_coded_formats():
    assert standardize_phone("+442071838750") == "+442071838750"
    assert standardize_phone("0044 20 7183 8750") == "+442071838750"
    assert standardize_phone("+34 612 45 89 07") == "+34612458907"
    assert standardize_phone("+1 415-555-2671") == "+14155552671"
    assert standardize_phone("0033 1 23 45 67 89") == "+33123456789"


def test_standardize_phone_rejects_invalid_numbers():
    assert standardize_phone("") is None
    assert standardize_phone("123") is None
    assert standardize_phone("6124589070000") is None


def test_email_validation():
    assert is_valid_email("jane.doe@example.com") is True
    assert is_valid_email("jane.doe@sub.example.com") is True
    assert is_valid_email("no-at-sign.com") is False
    assert is_valid_email("no-domain@") is False
    assert is_valid_email("has space@example.com") is False
    assert is_valid_email("bad@domain") is False
    assert is_valid_email("") is False


def test_transform_candidate_row_end_to_end():
    row = {
        "submission_id": "sub_1",
        "candidate_name": " john smith ",
        "email": "john.smith@example.com",
        "phone": "020 7183 8750",
        "linkedin": "linkedin.com/in/johnsmith",
        "github": "github.com/johnsmith",
    }

    result = transform_candidate_row(row)

    assert result["submission_id"] == "sub_1"
    assert result["candidate_name"] == "JOHN SMITH"
    assert result["email"] == "john.smith@example.com"
    assert result["is_email_valid"] is True
    assert result["phone"] == "+442071838750"
    assert result["is_phone_valid"] is True


def test_transform_candidate_row_handles_missing_and_invalid_fields():
    row = {
        "submission_id": "sub_2",
        "candidate_name": "",
        "email": "not an email",
        "phone": "",
        "linkedin": "",
        "github": "",
    }

    result = transform_candidate_row(row)

    assert result["candidate_name"] == ""
    assert result["is_email_valid"] is False
    assert result["phone"] is None
    assert result["is_phone_valid"] is False
