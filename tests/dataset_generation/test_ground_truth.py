"""
Tests for the record of what was generated.

The point of the file is that it survives a change to the spec code, so the
cases here are about reading back exactly what was written - inconsistency
types included, and an empty list when none were planted.
"""

from dataset_generation.ground_truth import append_entry, read_entries, recorded_ids

SPEC = {
    "id": "001",
    "folder": "inconsistent",
    "role": "Data Engineer",
    "seniority": "Senior",
    "years": "6",
    "location": {"city": "Bristol", "country": "United Kingdom", "phone": "+44"},
    "github": True,
    "inconsistency_types": ["date_overlap", "ai_text"],
}


def write(path, **overrides):
    append_entry(
        path,
        spec={**SPEC, **overrides.pop("spec", {})},
        filename=overrides.pop("filename", "cv_001_data_engineer_senior.pdf"),
    )


def test_nothing_is_recorded_before_anything_is_generated(tmp_path):
    assert read_entries(tmp_path / "ground_truth.csv") == []
    assert recorded_ids(tmp_path / "ground_truth.csv") == set()


def test_a_generated_cv_is_recorded(tmp_path):
    path = tmp_path / "ground_truth.csv"

    write(path)

    (entry,) = read_entries(path)
    assert entry["id"] == "001"
    assert entry["filename"] == "cv_001_data_engineer_senior.pdf"
    assert entry["folder"] == "inconsistent"


def test_the_planted_inconsistencies_are_recorded(tmp_path):
    """The column that makes per-type results possible."""
    path = tmp_path / "ground_truth.csv"

    write(path)

    assert read_entries(path)[0]["inconsistency_types"] == ["date_overlap", "ai_text"]


def test_a_legitimate_cv_records_no_inconsistencies(tmp_path):
    path = tmp_path / "ground_truth.csv"

    write(path, spec={"folder": "legitimate", "inconsistency_types": []})

    assert read_entries(path)[0]["inconsistency_types"] == []


def test_the_candidate_shape_is_recorded_alongside_the_flaws(tmp_path):
    """Lets results be broken down by role or seniority, not only by type."""
    path = tmp_path / "ground_truth.csv"

    write(path)

    entry = read_entries(path)[0]
    assert entry["role"] == "Data Engineer"
    assert entry["seniority"] == "Senior"
    assert entry["location"] == "Bristol"


def test_entries_accumulate_in_the_order_they_were_made(tmp_path):
    path = tmp_path / "ground_truth.csv"

    write(path)
    write(path, spec={"id": "002"}, filename="cv_002_bi_analyst_mid.pdf")

    assert [e["id"] for e in read_entries(path)] == ["001", "002"]


def test_the_header_is_written_once(tmp_path):
    path = tmp_path / "ground_truth.csv"

    write(path)
    write(path, spec={"id": "002"})

    assert path.read_text().count("inconsistency_types") == 1


def test_recorded_ids_are_what_the_generator_skips(tmp_path):
    path = tmp_path / "ground_truth.csv"

    write(path)
    write(path, spec={"id": "002"})

    assert recorded_ids(path) == {"001", "002"}


def test_the_record_survives_a_filename_that_no_longer_matches_the_spec(tmp_path):
    """The whole reason the file exists: names drift, the record does not."""
    path = tmp_path / "ground_truth.csv"

    write(path, filename="cv_001_under_an_old_role_naming.pdf")

    assert read_entries(path)[0]["filename"] == "cv_001_under_an_old_role_naming.pdf"
    assert read_entries(path)[0]["inconsistency_types"] == ["date_overlap", "ai_text"]
