"""
Tests for the two bronze store adapters.

Each one is a thin front for the GCS and BigQuery helpers, so the helpers
are replaced and what is checked is the delegation: the table each write
lands in, the schema it is created with, and the blob cache that keeps a
download from listing the bucket again.
"""

import pytest

from bronze.assets import extract_cv_text, extract_entities


class Blob:
    def __init__(self, name):
        self.name = name


class Recorder:
    """Collects every call the adapters make to the io helpers."""

    def __init__(self):
        self.ensured = []
        self.inserted = []
        self.archived = []
        self.deleted = []


@pytest.fixture
def cv_store(monkeypatch):
    """A CV text store with the io helpers replaced."""
    recorder = Recorder()
    blobs = [Blob("cvs/raw/legitimate/a.pdf"), Blob("cvs/raw/legitimate/b.pdf")]

    monkeypatch.setattr(extract_cv_text, "list_pdfs_in_gcs", lambda folder: blobs)
    monkeypatch.setattr(
        extract_cv_text, "download_pdf_from_gcs", lambda blob: f"bytes:{blob.name}"
    )
    monkeypatch.setattr(
        extract_cv_text, "get_processed_versions", lambda table: {"cv_1": "hash"}
    )
    monkeypatch.setattr(
        extract_cv_text, "delete_cv_data", lambda sid: recorder.deleted.append(sid)
    )
    monkeypatch.setattr(
        extract_cv_text,
        "ensure_table",
        lambda table, schema: recorder.ensured.append((table, schema)),
    )
    monkeypatch.setattr(
        extract_cv_text,
        "insert_rows_to_bigquery",
        lambda table, rows: recorder.inserted.append((table, rows)),
    )
    return extract_cv_text.GcsBigQueryCvTextStore(), recorder


@pytest.fixture
def entity_store(monkeypatch):
    """An entities store with the io helpers replaced."""
    recorder = Recorder()

    monkeypatch.setattr(
        extract_entities, "get_all_cv_texts", lambda: [{"submission_id": "cv_1"}]
    )
    monkeypatch.setattr(
        extract_entities, "get_processed_submission_ids", lambda table: {"cv_1"}
    )
    monkeypatch.setattr(
        extract_entities,
        "ensure_table",
        lambda table, schema: recorder.ensured.append((table, schema)),
    )
    monkeypatch.setattr(
        extract_entities,
        "insert_rows_to_bigquery",
        lambda table, rows: recorder.inserted.append((table, rows)),
    )
    monkeypatch.setattr(
        extract_entities,
        "save_json_to_gcs",
        lambda payload, path: recorder.archived.append((payload, path)),
    )
    return extract_entities.BigQueryEntitiesStore(), recorder


# ── the CV text store ─────────────────────────────────────────────────────
def test_listing_returns_the_blob_names(cv_store):
    store, _ = cv_store

    assert store.list_pdf_names("legitimate") == [
        "cvs/raw/legitimate/a.pdf",
        "cvs/raw/legitimate/b.pdf",
    ]


def test_a_download_reuses_the_blob_from_the_listing(cv_store):
    """Otherwise every download would list the bucket again."""
    store, _ = cv_store
    store.list_pdf_names("legitimate")

    assert store.download_pdf("cvs/raw/legitimate/a.pdf") == (
        "bytes:cvs/raw/legitimate/a.pdf"
    )


def test_downloading_a_blob_that_was_never_listed_fails(cv_store):
    store, _ = cv_store

    with pytest.raises(KeyError):
        store.download_pdf("never-listed.pdf")


def test_processed_versions_come_from_the_cv_texts_table(cv_store):
    store, _ = cv_store

    assert store.read_processed_versions() == {"cv_1": "hash"}


def test_deleting_a_cv_clears_it_from_every_table(cv_store):
    store, recorder = cv_store

    store.delete_cv("cv_1")

    assert recorder.deleted == ["cv_1"]


def test_cv_texts_are_appended_to_a_table_that_is_created_first(cv_store):
    """Bronze is appended to, so unlike silver the write does not create it."""
    store, recorder = cv_store

    store.insert_cv_texts([{"submission_id": "cv_1"}])

    ensured_table, schema = recorder.ensured[0]
    inserted_table, rows = recorder.inserted[0]
    assert ensured_table == inserted_table
    assert ensured_table.endswith("raw_cv_texts")
    assert schema is extract_cv_text.CV_TEXTS_SCHEMA
    assert rows == [{"submission_id": "cv_1"}]


# ── the entities store ────────────────────────────────────────────────────
def test_cv_texts_are_read_fresh_from_the_table(entity_store):
    store, _ = entity_store

    assert store.read_cv_texts() == [{"submission_id": "cv_1"}]


def test_processed_ids_come_from_the_work_experience_table(entity_store):
    store, _ = entity_store

    assert store.read_processed_submission_ids() == {"cv_1"}


ENTITY_WRITES = [
    ("insert_candidates", "raw_candidates"),
    ("insert_work_experience", "raw_work_experience"),
    ("insert_skills", "raw_skills"),
]


@pytest.mark.parametrize(
    "method,table", ENTITY_WRITES, ids=[t for _, t in ENTITY_WRITES]
)
def test_each_entity_kind_goes_to_its_own_table(entity_store, method, table):
    store, recorder = entity_store

    getattr(store, method)([{"submission_id": "cv_1"}])

    ensured_table, schema = recorder.ensured[0]
    assert ensured_table.endswith(table)
    assert schema is extract_entities.SCHEMAS[table]
    assert recorder.inserted[0][0] == ensured_table


def test_an_extraction_is_archived_under_its_submission_id(entity_store):
    store, recorder = entity_store

    store.archive_extraction("cv_1", {"candidate_name": "Ada"})

    assert recorder.archived == [
        ({"candidate_name": "Ada"}, "cvs/extracted/entities/cv_1.json")
    ]


# ── the PDF reader ────────────────────────────────────────────────────────
def pdf_bytes(text: str) -> bytes:
    """A real one-page PDF, rendered the way the dataset is."""
    import tempfile
    from pathlib import Path

    from dataset_generation.text_to_pdf import text_to_pdf

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "cv.pdf"
        text_to_pdf(text, str(path))
        return path.read_bytes()


def test_the_text_of_a_pdf_is_read_back():
    read = extract_cv_text.read_pdf_text(pdf_bytes("Ada Lovelace\nData Engineer"))

    assert "Ada Lovelace" in read
    assert "Data Engineer" in read


def test_bytes_that_are_not_a_pdf_are_rejected():
    with pytest.raises(Exception):
        extract_cv_text.read_pdf_text(b"not a pdf")


def test_the_raw_text_store_archives_beside_the_entity_archive(cv_store, monkeypatch):
    store, recorder = cv_store
    monkeypatch.setattr(
        extract_cv_text,
        "save_json_to_gcs",
        lambda payload, path: recorder.archived.append((payload, path)),
    )

    store.archive_raw_text("cv_1", {"raw_text": "CV TEXT"})

    assert recorder.archived == [
        ({"raw_text": "CV TEXT"}, "cvs/extracted/raw_text/cv_1.json")
    ]
