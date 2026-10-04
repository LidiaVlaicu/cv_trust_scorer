"""
End-to-end test of the entity pipeline against an in-memory fake store and a
fake extractor — no BigQuery, no GCS, and no Claude calls, so running this
suite costs nothing.
"""

from datetime import datetime, timezone

from pydantic import ValidationError

from bronze.assets.extract_entities import (
    build_entity_rows,
    run_extract_entities,
)
from bronze.schemas import ExtractedCV

FIXED_TIME = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class FakeEntitiesStore:
    """In-memory EntitiesStore. Records what the pipeline would write."""

    def __init__(
        self,
        cv_texts: list[dict],
        processed: set[str] | None = None,
    ) -> None:
        self._cv_texts = cv_texts
        self._processed = processed or set()
        self.candidates: list[dict] = []
        self.work_experience: list[dict] = []
        self.skills: list[dict] = []
        self.archived: list[str] = []

    def read_cv_texts(self) -> list[dict]:
        return self._cv_texts

    def read_processed_submission_ids(self) -> set[str]:
        return self._processed

    def insert_candidates(self, rows: list[dict]) -> None:
        self.candidates.extend(rows)

    def insert_work_experience(self, rows: list[dict]) -> None:
        self.work_experience.extend(rows)

    def insert_skills(self, rows: list[dict]) -> None:
        self.skills.extend(rows)

    def archive_extraction(self, submission_id: str, payload: dict) -> None:
        self.archived.append(submission_id)


CV_TEXTS = [
    {"submission_id": "cv_1", "profile_type": "technical", "raw_text": "cv one"},
    {"submission_id": "cv_2", "profile_type": "technical", "raw_text": "cv two"},
    {"submission_id": "cv_3", "profile_type": "non_technical", "raw_text": "cv three"},
]

EXTRACTED = {
    "cv one": ExtractedCV(
        candidate_name="Ada Lovelace",
        email="ada@example.com",
        work_experience=[
            {
                "job_title": "Data Engineer",
                "company_name": "Monzo",
                "start_date": "August 2017",
                "end_date": "Present",
                "is_current": True,
            },
            {
                "job_title": "Analyst",
                "company_name": "Deloitte",
                "start_date": "January 2015",
                "end_date": "July 2017",
            },
        ],
        skills=["Python", "Power BI", "Underwater Welding"],
    ),
    "cv two": ExtractedCV(
        candidate_name="Grace Hopper",
        work_experience=[
            {"job_title": "Engineer", "company_name": "IBM", "start_date": "1944"}
        ],
        skills=["SQL"],
    ),
}


def _extract(raw_text: str) -> ExtractedCV:
    return EXTRACTED[raw_text]


def _run(store: FakeEntitiesStore, **kwargs):
    return run_extract_entities(
        store,
        extract=kwargs.pop("extract", _extract),
        now=lambda: FIXED_TIME,
        **kwargs,
    )


def test_writes_one_candidate_row_per_technical_cv():
    store = FakeEntitiesStore(CV_TEXTS)
    result = _run(store)

    assert [row["submission_id"] for row in store.candidates] == ["cv_1", "cv_2"]
    assert result["candidates_count"] == 2


def test_a_non_technical_cv_is_skipped_entirely():
    store = FakeEntitiesStore(CV_TEXTS)
    _run(store)

    assert "cv_3" not in {row["submission_id"] for row in store.candidates}
    assert "cv_3" not in store.archived


def test_a_cv_already_processed_is_skipped():
    store = FakeEntitiesStore(CV_TEXTS, processed={"cv_1"})
    result = _run(store)

    assert [row["submission_id"] for row in store.candidates] == ["cv_2"]
    assert result["work_experience_count"] == 1


def test_experience_ids_are_numbered_per_cv():
    store = FakeEntitiesStore(CV_TEXTS)
    _run(store)

    assert [row["experience_id"] for row in store.work_experience] == [
        "cv_1_job1",
        "cv_1_job2",
        "cv_2_job1",
    ]


def test_dates_are_kept_exactly_as_the_cv_wrote_them():
    store = FakeEntitiesStore(CV_TEXTS)
    _run(store)
    by_id = {row["experience_id"]: row for row in store.work_experience}

    assert by_id["cv_1_job1"]["start_date_raw"] == "August 2017"
    assert by_id["cv_1_job1"]["end_date_raw"] == "Present"


def test_skills_are_categorized_and_unknown_ones_fall_back_to_other():
    store = FakeEntitiesStore(CV_TEXTS)
    _run(store)
    by_name = {row["skill_name"]: row for row in store.skills}

    assert by_name["Python"]["skill_category"] == "language"
    assert by_name["Power BI"]["skill_category"] == "bi_analytics"
    assert by_name["Underwater Welding"]["skill_category"] == "other"


def test_skill_ids_are_built_from_the_submission_and_the_skill():
    store = FakeEntitiesStore(CV_TEXTS)
    _run(store)

    assert "cv_1_power_bi" in {row["skill_id"] for row in store.skills}


def test_each_processed_cv_is_archived_before_bigquery():
    store = FakeEntitiesStore(CV_TEXTS)
    _run(store)

    assert store.archived == ["cv_1", "cv_2"]


def test_a_cv_that_fails_validation_is_skipped_and_the_rest_continue():
    def _fails_on_cv_1(raw_text: str) -> ExtractedCV:
        if raw_text == "cv one":
            raise ValidationError.from_exception_data("ExtractedCV", [])
        return _extract(raw_text)

    store = FakeEntitiesStore(CV_TEXTS)
    reported: list[str] = []
    result = _run(store, extract=_fails_on_cv_1, report=reported.append)

    assert [row["submission_id"] for row in store.candidates] == ["cv_2"]
    assert result["candidates_count"] == 1
    assert any("[FAIL]" in message for message in reported)


def test_nothing_is_written_when_every_cv_is_already_processed():
    store = FakeEntitiesStore(CV_TEXTS, processed={"cv_1", "cv_2"})
    result = _run(store)

    assert store.candidates == []
    assert store.work_experience == []
    assert store.skills == []
    assert result == {
        "candidates_count": 0,
        "work_experience_count": 0,
        "skills_count": 0,
    }


def test_every_row_carries_the_injected_timestamp():
    store = FakeEntitiesStore(CV_TEXTS)
    _run(store)

    assert {row["extracted_at"] for row in store.candidates} == {
        FIXED_TIME.isoformat()
    }


def test_build_entity_rows_is_pure():
    """Same inputs, same output - safe to rerun."""
    cv_data = EXTRACTED["cv one"]

    first = build_entity_rows("cv_1", cv_data, FIXED_TIME)
    second = build_entity_rows("cv_1", cv_data, FIXED_TIME)

    assert first == second
