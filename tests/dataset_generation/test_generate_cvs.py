"""
Tests for the generation loop.

The skip is the part that matters: a CV whose PDF already exists must not be
regenerated, because every regeneration is a paid API call. Neither Claude
nor the PDF renderer is reached here - both are replaced, and the output
root is redirected into a temporary directory.
"""

import pytest

from dataset_generation import generate_cvs


class Recorder:
    """Stands in for the API call and the renderer."""

    def __init__(self, fail_on=()):
        self.prompted = []
        self.written = []
        self._fail_on = set(fail_on)

    def generate(self, prompt: str) -> str:
        self.prompted.append(prompt)
        return "CV TEXT"

    def render(self, text: str, output_path: str) -> None:
        if any(name in output_path for name in self._fail_on):
            raise RuntimeError("render failed")
        self.written.append(output_path)
        open(output_path, "w").close()


@pytest.fixture
def run(monkeypatch, tmp_path):
    """Runs main() against a temporary output root with both ends faked."""

    def go(total=4, fail_on=()):
        recorder = Recorder(fail_on)
        monkeypatch.setattr(generate_cvs, "OUTPUT_ROOT", tmp_path)
        monkeypatch.setattr(generate_cvs, "TOTAL_CVS", total)
        monkeypatch.setattr(generate_cvs, "generate_cv_text", recorder.generate)
        monkeypatch.setattr(generate_cvs, "text_to_pdf", recorder.render)
        generate_cvs.main()
        return recorder

    return go


def test_both_output_folders_are_created(run, tmp_path):
    run()

    assert (tmp_path / "inconsistent").is_dir()
    assert (tmp_path / "legitimate").is_dir()


def test_one_cv_is_generated_per_spec(run):
    recorder = run(total=4)

    assert len(recorder.written) == 4
    assert len(recorder.prompted) == 4


def test_every_cv_is_written_under_its_own_folder(run, tmp_path):
    recorder = run(total=4)

    for path in recorder.written:
        assert str(tmp_path) in path
        assert "/inconsistent/" in path or "/legitimate/" in path


def test_a_cv_whose_pdf_exists_is_not_generated_again(run, tmp_path):
    """The guard that keeps a repeated run from paying for the same CV twice."""
    first = run(total=4)

    second = run(total=4)

    assert len(first.written) == 4
    assert second.prompted == []


def test_a_failed_cv_does_not_stop_the_others(run):
    recorder = run(total=4, fail_on=["_001_"])

    assert len(recorder.written) >= 3


def test_nothing_is_generated_when_the_dataset_is_empty(run):
    recorder = run(total=0)

    assert recorder.prompted == []
