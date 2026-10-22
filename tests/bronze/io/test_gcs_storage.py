"""
Tests for the bronze GCS adapter.

A fake bucket stands in for Cloud Storage. What matters here is the prefix
the listing uses, the filtering that keeps non-PDF objects out, and the way
a JSON archive is serialized before upload.
"""

import json

import pytest

from bronze.io import gcs_storage as adapter


class FakeBlob:
    def __init__(self, name, data=b""):
        self.name = name
        self._data = data
        self.uploaded = None
        self.content_type = None

    def download_as_bytes(self):
        return self._data

    def upload_from_string(self, data, content_type=None):
        self.uploaded = data
        self.content_type = content_type


class FakeBucket:
    def __init__(self, blobs):
        self._blobs = blobs
        self.prefixes: list[str] = []
        self.named: list[str] = []

    def list_blobs(self, prefix=None):
        self.prefixes.append(prefix)
        return self._blobs

    def blob(self, name):
        self.named.append(name)
        created = FakeBlob(name)
        self._blobs.append(created)
        return created


@pytest.fixture
def bucket(monkeypatch):
    def install(blobs=()):
        fake = FakeBucket(list(blobs))
        monkeypatch.setattr(
            adapter.storage,
            "Client",
            lambda: type("C", (), {"bucket": lambda s, n: fake})(),
        )
        return fake

    return install


def test_only_pdfs_are_returned(bucket):
    bucket([FakeBlob("a.pdf"), FakeBlob("notes.txt"), FakeBlob("b.pdf")])

    found = adapter.list_pdfs_in_gcs("legitimate")

    assert [blob.name for blob in found] == ["a.pdf", "b.pdf"]


def test_a_folder_with_no_pdfs_lists_nothing(bucket):
    bucket([FakeBlob("notes.txt")])

    assert adapter.list_pdfs_in_gcs("legitimate") == []


def test_the_listing_is_scoped_to_the_folder_asked_for(bucket):
    fake = bucket([])

    adapter.list_pdfs_in_gcs("inconsistent")

    assert fake.prefixes == ["cvs/raw/inconsistent/"]


def test_a_pdf_is_downloaded_as_bytes():
    assert adapter.download_pdf_from_gcs(FakeBlob("a.pdf", b"%PDF-1.7")) == b"%PDF-1.7"


def test_an_archive_is_written_as_json_at_the_path_given(bucket):
    fake = bucket([])

    adapter.save_json_to_gcs({"submission_id": "cv_1"}, "cvs/extracted/cv_1.json")

    assert fake.named == ["cvs/extracted/cv_1.json"]
    assert json.loads(fake._blobs[0].uploaded) == {"submission_id": "cv_1"}


def test_an_archive_is_tagged_as_json_for_the_browser(bucket):
    fake = bucket([])

    adapter.save_json_to_gcs({}, "cvs/extracted/cv_1.json")

    assert fake._blobs[0].content_type == "application/json"


def test_values_json_cannot_serialize_are_stringified(bucket):
    """Timestamps reach this adapter as datetimes and must not stop the write."""
    from datetime import datetime, timezone

    fake = bucket([])

    adapter.save_json_to_gcs(
        {"extracted_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}, "a.json"
    )

    assert "2026-01-01" in fake._blobs[0].uploaded
