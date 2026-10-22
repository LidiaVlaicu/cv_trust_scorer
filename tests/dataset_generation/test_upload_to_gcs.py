"""
Tests for the dataset upload.

Nothing reaches Cloud Storage, and nothing reads the real data/ folder: each
test runs in a temporary working directory with a fake bucket. The skip for
an object that already exists is what keeps a repeated run cheap.
"""

import pytest

from dataset_generation import upload_to_gcs


class FakeBlob:
    def __init__(self, name, already_there):
        self.name = name
        self._already_there = already_there
        self.uploaded_from = None

    def exists(self):
        return self._already_there

    def upload_from_filename(self, path):
        if path.endswith("broken.pdf"):
            raise RuntimeError("upload failed")
        self.uploaded_from = path


class FakeBucket:
    def __init__(self, already_there=()):
        self.blobs: list[FakeBlob] = []
        self._already_there = set(already_there)

    def blob(self, name):
        created = FakeBlob(name, name in self._already_there)
        self.blobs.append(created)
        return created

    @property
    def uploaded(self):
        return [b.name for b in self.blobs if b.uploaded_from]


@pytest.fixture
def upload(monkeypatch, tmp_path):
    """Runs the upload against a temporary data/ folder and a fake bucket."""

    def go(files: dict[str, list[str]], already_there=(), ground_truth=None):
        for folder, names in files.items():
            directory = tmp_path / "data" / folder
            directory.mkdir(parents=True)
            for name in names:
                (directory / name).write_bytes(b"%PDF-1.7")

        if ground_truth is not None:
            (tmp_path / "data").mkdir(exist_ok=True)
            (tmp_path / "data" / "ground_truth.csv").write_text(ground_truth)

        bucket = FakeBucket(already_there)
        monkeypatch.setattr(
            upload_to_gcs.storage,
            "Client",
            lambda: type("C", (), {"bucket": lambda s, n: bucket})(),
        )
        monkeypatch.chdir(tmp_path)
        upload_to_gcs.upload_cvs_to_gcs()
        return bucket

    return go


def test_each_pdf_is_uploaded_under_its_folder(upload):
    bucket = upload({"legitimate": ["cv_001.pdf"], "inconsistent": ["cv_002.pdf"]})

    assert set(bucket.uploaded) == {
        "cvs/raw/legitimate/cv_001.pdf",
        "cvs/raw/inconsistent/cv_002.pdf",
    }


def test_an_object_already_in_the_bucket_is_skipped(upload):
    bucket = upload(
        {"legitimate": ["cv_001.pdf", "cv_002.pdf"]},
        already_there=["cvs/raw/legitimate/cv_001.pdf"],
    )

    assert bucket.uploaded == ["cvs/raw/legitimate/cv_002.pdf"]


def test_a_missing_folder_is_reported_rather_than_fatal(upload):
    """A half-built dataset should still upload the half that exists."""
    bucket = upload({"legitimate": ["cv_001.pdf"]})

    assert bucket.uploaded == ["cvs/raw/legitimate/cv_001.pdf"]


def test_a_failed_upload_does_not_stop_the_rest(upload):
    bucket = upload({"legitimate": ["broken.pdf", "cv_002.pdf"]})

    assert bucket.uploaded == ["cvs/raw/legitimate/cv_002.pdf"]


def test_files_that_are_not_pdfs_are_ignored(upload, tmp_path):
    (tmp_path / "data" / "legitimate").mkdir(parents=True)
    (tmp_path / "data" / "legitimate" / "notes.txt").write_text("x")

    bucket = upload({"inconsistent": ["cv_001.pdf"]})

    assert bucket.uploaded == ["cvs/raw/inconsistent/cv_001.pdf"]


def test_an_empty_dataset_uploads_nothing(upload):
    bucket = upload({"legitimate": [], "inconsistent": []})

    assert bucket.uploaded == []


# ── the ground truth file ─────────────────────────────────────────────────
def test_the_ground_truth_goes_up_beside_the_cvs(upload, tmp_path):
    bucket = upload({"legitimate": ["cv_001.pdf"]}, ground_truth="id,folder\n001,x\n")

    assert "cvs/raw/ground_truth.csv" in bucket.uploaded


def test_it_sits_above_the_folders_so_the_pdf_listing_ignores_it(upload):
    bucket = upload({"legitimate": []}, ground_truth="id\n001\n")

    (name,) = bucket.uploaded
    assert name == "cvs/raw/ground_truth.csv"
    assert "/legitimate/" not in name and "/inconsistent/" not in name


def test_a_missing_ground_truth_is_a_warning_not_a_failure(upload, capsys):
    bucket = upload({"legitimate": ["cv_001.pdf"]})

    assert "cvs/raw/ground_truth.csv" not in bucket.uploaded
    assert "[WARN]" in capsys.readouterr().out


def test_an_existing_ground_truth_in_the_bucket_is_overwritten(upload):
    """A stale copy would describe CVs that are no longer there."""
    bucket = upload(
        {"legitimate": []},
        ground_truth="id\n001\n",
        already_there=["cvs/raw/ground_truth.csv"],
    )

    assert "cvs/raw/ground_truth.csv" in bucket.uploaded
