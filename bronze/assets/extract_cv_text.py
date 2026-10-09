"""
GCS PDFs -> bronze.raw_cv_texts

Structure: a pure core and a thin I/O shell.

    decide_action()         pure - new, unchanged or changed
    build_cv_text_row()     pure - one PDF's row
    CvTextStore             protocol - every read/write this needs
    GcsBigQueryCvTextStore  the only code here touching GCS and BigQuery
    run_extract_raw_text()  orchestration, with dependencies injected
    extract_raw_text        Dagster asset - wires the real ones

The store and the PDF reader are injected, so the whole run works against an
in-memory fake with no GCS and no BigQuery.
"""

from datetime import datetime, timezone
from typing import Callable, Literal, Protocol

import fitz
from dagster import asset, get_dagster_logger
from google.cloud import bigquery

from bronze.rules.cv_analysis import classify_profile, compute_file_hash
from bronze.io.gcs_storage import (
    BUCKET_NAME,
    download_pdf_from_gcs,
    list_pdfs_in_gcs,
)
from bronze.io.bigquery_persistence import (
    BRONZE_DATASET,
    PROJECT_ID,
    delete_cv_data,
    ensure_table,
    get_processed_versions,
    insert_rows_to_bigquery,
)

CV_TEXTS_TABLE = "raw_cv_texts"
# Matches the live table. Bronze appends, so the table has to exist before the
# first insert - see ensure_table.
CV_TEXTS_SCHEMA = [
    bigquery.SchemaField("submission_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("content_hash", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("cv_file_path", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("submission_timestamp", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("raw_text", "STRING"),
    bigquery.SchemaField("profile_type", "STRING"),
    bigquery.SchemaField("folder", "STRING"),
]
FOLDERS = ("inconsistent", "legitimate")

Action = Literal["new", "unchanged", "changed"]


# ── Pure core ─────────────────────────────────────────────────────────────
def decide_action(
    submission_id: str,
    current_hash: str,
    existing: dict[str, str],
) -> Action:
    """
    What to do with one PDF, given the hashes already in the warehouse.

    "unchanged" is skipped, "changed" has its old rows deleted first, "new"
    is simply processed.
    """
    if submission_id not in existing:
        return "new"
    if existing[submission_id] == current_hash:
        return "unchanged"
    return "changed"


def build_cv_text_row(
    submission_id: str,
    raw_text: str,
    content_hash: str,
    blob_name: str,
    folder: str,
    submitted_at: datetime,
    bucket: str,
) -> dict:
    """One raw_cv_texts row. Pure: same inputs always give the same output."""
    return {
        "submission_id": submission_id,
        "content_hash": content_hash,
        "profile_type": classify_profile(raw_text),
        "cv_file_path": f"gs://{bucket}/{blob_name}",
        "submission_timestamp": submitted_at.isoformat(),
        "raw_text": raw_text,
        "folder": folder,
    }


# ── I/O boundary ──────────────────────────────────────────────────────────
class CvTextStore(Protocol):
    """Everything the raw_cv_texts pipeline needs from GCS and BigQuery."""

    bucket: str

    def list_pdf_names(self, folder: str) -> list[str]:
        """The blob names of every PDF in `folder`."""

    def download_pdf(self, blob_name: str) -> bytes:
        """The bytes of one PDF."""

    def read_processed_versions(self) -> dict[str, str]:
        """{submission_id: content_hash} already in raw_cv_texts."""

    def delete_cv(self, submission_id: str) -> None:
        """Removes a CV from every bronze table, before it is reprocessed."""

    def insert_cv_texts(self, rows: list[dict]) -> None:
        """Appends rows to raw_cv_texts."""


class GcsBigQueryCvTextStore:
    """CvTextStore backed by GCS and BigQuery."""

    def __init__(self, bucket: str = BUCKET_NAME) -> None:
        self.bucket = bucket
        # Blobs from the last listing, so downloading doesn't re-fetch them.
        self._blobs: dict[str, object] = {}

    def list_pdf_names(self, folder: str) -> list[str]:
        blobs = list_pdfs_in_gcs(folder)
        self._blobs.update({blob.name: blob for blob in blobs})
        return [blob.name for blob in blobs]

    def download_pdf(self, blob_name: str) -> bytes:
        return download_pdf_from_gcs(self._blobs[blob_name])

    def read_processed_versions(self) -> dict[str, str]:
        return get_processed_versions(CV_TEXTS_TABLE)

    def delete_cv(self, submission_id: str) -> None:
        delete_cv_data(submission_id)

    def insert_cv_texts(self, rows: list[dict]) -> None:
        table = f"{PROJECT_ID}.{BRONZE_DATASET}.{CV_TEXTS_TABLE}"
        ensure_table(table, CV_TEXTS_SCHEMA)
        insert_rows_to_bigquery(table, rows)


def read_pdf_text(pdf_bytes: bytes) -> str:
    """All text in a PDF, pages joined. The only PyMuPDF call in the project."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        return "".join(page.get_text() for page in doc)
    finally:
        doc.close()


# ── Orchestration (dependencies injected) ─────────────────────────────────
def run_extract_raw_text(
    store: CvTextStore,
    *,
    extract_text: Callable[[bytes], str] = read_pdf_text,
    folders: tuple[str, ...] = FOLDERS,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    report: Callable[[str], None] = lambda message: None,
) -> list[dict]:
    """
    Reads every PDF, skips the unchanged ones, and writes the rest to
    raw_cv_texts. The store, the PDF reader and the clock are injected so
    this runs with no GCS, no BigQuery and no Dagster.
    """
    existing = store.read_processed_versions()
    report(f"Already processed: {len(existing)} CVs")

    rows: list[dict] = []
    submitted_at = now()

    for folder in folders:
        for blob_name in store.list_pdf_names(folder):
            filename = blob_name.split("/")[-1]
            submission_id = filename.removesuffix(".pdf")

            try:
                pdf_bytes = store.download_pdf(blob_name)
                current_hash = compute_file_hash(pdf_bytes)
                action = decide_action(submission_id, current_hash, existing)

                if action == "unchanged":
                    report(f"[SKIP unchanged] {submission_id}")
                    continue
                if action == "changed":
                    report(f"[REPROCESS changed] {submission_id}")
                    store.delete_cv(submission_id)

                raw_text = extract_text(pdf_bytes)
                if not raw_text.strip():
                    report(f"[SKIP empty text] {filename}")
                    continue

                rows.append(
                    build_cv_text_row(
                        submission_id,
                        raw_text,
                        current_hash,
                        blob_name,
                        folder,
                        submitted_at,
                        store.bucket,
                    )
                )
                report(f"[OK] {submission_id}")

            except Exception as e:
                report(f"[FAIL] {filename}: {e}")

    if rows:
        store.insert_cv_texts(rows)
        report(f"Inserted {len(rows)} rows")

    return rows


# ── ASSET: extract_raw_text ───────────────────────────────────────────────
@asset
def extract_raw_text():
    """
    Reads every CV PDF from GCS, extracts its text, labels the profile type
    and loads the result into bronze raw_cv_texts.

    A CV whose content hash is unchanged is skipped; a changed one has its
    old rows deleted from every bronze table before being reprocessed.
    """
    return run_extract_raw_text(
        GcsBigQueryCvTextStore(),
        report=get_dagster_logger().info,
    )
