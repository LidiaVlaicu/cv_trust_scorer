"""
End-to-end test of the raw_cv_texts pipeline against an in-memory fake
store — no GCS, no BigQuery, no PDFs on disk.

The point of this file is the new/unchanged/changed decision: it is the only
code in the project that can silently lose rows, and it was untestable until
the store was injected.
"""

from datetime import datetime, timezone

from bronze.assets.extract_cv_text import (
    build_cv_text_row,
    decide_action,
    run_extract_raw_text,
)
from bronze.rules.cv_analysis import compute_file_hash

FIXED_TIME = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

TECHNICAL_TEXT = "Data engineer. Python, BigQuery, dbt and Airflow every day."


class FakeCvTextStore:
    """In-memory CvTextStore. Records what the pipeline would write."""

    bucket = "test-bucket"

    def __init__(
        self,
        pdfs: dict[str, bytes],
        processed: dict[str, str] | None = None,
    ) -> None:
        self._pdfs = pdfs
        self._processed = processed or {}
        self.written: list[dict] = []
        self.write_count = 0
        self.deleted: list[str] = []
        self.downloaded: list[str] = []

    def list_pdf_names(self, folder: str) -> list[str]:
        return [name for name in self._pdfs if f"/{folder}/" in name]

    def download_pdf(self, blob_name: str) -> bytes:
        self.downloaded.append(blob_name)
        return self._pdfs[blob_name]

    def read_processed_versions(self) -> dict[str, str]:
        return self._processed

    def delete_cv(self, submission_id: str) -> None:
        self.deleted.append(submission_id)

    def insert_cv_texts(self, rows: list[dict]) -> None:
        self.written.extend(rows)
        self.write_count += 1


PDFS = {
    "cvs/raw/inconsistent/cv_1.pdf": b"%PDF cv one",
    "cvs/raw/legitimate/cv_2.pdf": b"%PDF cv two",
}


def _text_for(pdf_bytes: bytes) -> str:
    return f"{TECHNICAL_TEXT} {pdf_bytes.decode()}"


def _run(store: FakeCvTextStore, **kwargs):
    return run_extract_raw_text(
        store,
        extract_text=kwargs.pop("extract_text", _text_for),
        now=lambda: FIXED_TIME,
        **kwargs,
    )


# ── the decision, on its own ───────────────────────────────────────────────
def test_decide_action_calls_an_unseen_cv_new():
    assert decide_action("cv_1", "aaa", {}) == "new"


def test_decide_action_calls_a_matching_hash_unchanged():
    assert decide_action("cv_1", "aaa", {"cv_1": "aaa"}) == "unchanged"


def test_decide_action_calls_a_different_hash_changed():
    assert decide_action("cv_1", "bbb", {"cv_1": "aaa"}) == "changed"


# ── the whole run ──────────────────────────────────────────────────────────
def test_first_run_writes_one_row_per_pdf():
    store = FakeCvTextStore(PDFS)
    rows = _run(store)

    assert store.write_count == 1
    assert len(rows) == 2
    assert {row["submission_id"] for row in rows} == {"cv_1", "cv_2"}
    assert store.deleted == []


def test_rows_record_the_folder_and_the_gcs_path():
    store = FakeCvTextStore(PDFS)
    by_id = {row["submission_id"]: row for row in _run(store)}

    assert by_id["cv_1"]["folder"] == "inconsistent"
    assert by_id["cv_2"]["folder"] == "legitimate"
    assert (
        by_id["cv_1"]["cv_file_path"]
        == "gs://test-bucket/cvs/raw/inconsistent/cv_1.pdf"
    )


def test_an_unchanged_cv_is_skipped_and_never_rewritten():
    unchanged = {
        "cv_1": compute_file_hash(PDFS["cvs/raw/inconsistent/cv_1.pdf"]),
        "cv_2": compute_file_hash(PDFS["cvs/raw/legitimate/cv_2.pdf"]),
    }
    store = FakeCvTextStore(PDFS, processed=unchanged)
    rows = _run(store)

    assert rows == []
    assert store.write_count == 0
    assert store.deleted == []


def test_a_changed_cv_is_deleted_before_being_rewritten():
    store = FakeCvTextStore(PDFS, processed={"cv_1": "a-stale-hash"})
    rows = _run(store)

    assert store.deleted == ["cv_1"]
    assert {row["submission_id"] for row in rows} == {"cv_1", "cv_2"}
    assert len(rows) == 2  # one row for cv_1, not two


def test_the_stored_hash_is_the_new_one_after_a_change():
    """A stale hash left behind would make the CV reprocess forever."""
    store = FakeCvTextStore(PDFS, processed={"cv_1": "a-stale-hash"})
    by_id = {row["submission_id"]: row for row in _run(store)}

    expected = compute_file_hash(PDFS["cvs/raw/inconsistent/cv_1.pdf"])
    assert by_id["cv_1"]["content_hash"] == expected


def test_a_pdf_with_no_text_is_skipped():
    store = FakeCvTextStore(PDFS)
    rows = _run(store, extract_text=lambda pdf_bytes: "   \n  ")

    assert rows == []
    assert store.write_count == 0


def test_one_unreadable_pdf_does_not_stop_the_others():
    def _fails_on_cv_1(pdf_bytes: bytes) -> str:
        if b"one" in pdf_bytes:
            raise RuntimeError("corrupt PDF")
        return _text_for(pdf_bytes)

    store = FakeCvTextStore(PDFS)
    reported: list[str] = []
    rows = _run(store, extract_text=_fails_on_cv_1, report=reported.append)

    assert [row["submission_id"] for row in rows] == ["cv_2"]
    assert any("[FAIL]" in message for message in reported)


def test_a_failed_cv_is_not_left_half_deleted_in_the_report():
    """A changed CV that then fails should be visible, not silent."""
    store = FakeCvTextStore(PDFS, processed={"cv_1": "a-stale-hash"})
    reported: list[str] = []
    _run(
        store,
        extract_text=lambda pdf_bytes: (_ for _ in ()).throw(RuntimeError("boom")),
        report=reported.append,
    )

    assert store.deleted == ["cv_1"]
    assert sum("[FAIL]" in message for message in reported) == 2


def test_every_row_carries_the_injected_timestamp():
    store = FakeCvTextStore(PDFS)
    rows = _run(store)

    assert {row["submission_timestamp"] for row in rows} == {FIXED_TIME.isoformat()}


def test_profile_type_is_set_from_the_text():
    store = FakeCvTextStore({"cvs/raw/legitimate/cv_9.pdf": b"%PDF nine"})
    rows = _run(store, extract_text=lambda pdf_bytes: "Baker. Bread, cakes, pastry.")

    assert rows[0]["profile_type"] == "non_technical"


def test_build_cv_text_row_is_pure():
    """Same inputs, same output - safe to rerun."""
    args = ("cv_1", TECHNICAL_TEXT, "hash", "cvs/raw/x/cv_1.pdf", "x", FIXED_TIME, "b")

    assert build_cv_text_row(*args) == build_cv_text_row(*args)
