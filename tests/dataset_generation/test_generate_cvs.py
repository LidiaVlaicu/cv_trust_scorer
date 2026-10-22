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

    def go(total=4, fail_on=(), argv=("--yes",)):
        recorder = Recorder(fail_on)
        monkeypatch.setattr(generate_cvs, "OUTPUT_ROOT", tmp_path)
        monkeypatch.setattr(generate_cvs, "GROUND_TRUTH", tmp_path / "ground_truth.csv")
        monkeypatch.setattr(generate_cvs, "TOTAL_CVS", total)
        monkeypatch.setattr(generate_cvs, "generate_cv_text", recorder.generate)
        monkeypatch.setattr(generate_cvs, "text_to_pdf", recorder.render)
        generate_cvs.main(list(argv))
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


def test_every_generated_cv_is_recorded_in_the_ground_truth(run, tmp_path):
    from dataset_generation.ground_truth import read_entries

    recorder = run(total=4)

    entries = read_entries(tmp_path / "ground_truth.csv")
    assert len(entries) == len(recorder.written)


def test_the_ground_truth_records_what_each_cv_carries(run, tmp_path):
    from dataset_generation.ground_truth import read_entries

    run(total=4)

    entries = read_entries(tmp_path / "ground_truth.csv")
    assert all(e["folder"] in {"legitimate", "inconsistent"} for e in entries)
    assert any(e["inconsistency_types"] for e in entries)


def test_a_cv_in_the_ground_truth_is_not_generated_again(run, tmp_path):
    """The skip no longer depends on a filename the spec code may have changed."""
    run(total=4)
    for pdf in tmp_path.rglob("*.pdf"):
        pdf.unlink()

    second = run(total=4)

    assert second.prompted == []


# ── the cost confirmation ─────────────────────────────────────────────────
def test_nothing_is_generated_when_the_answer_is_no(run, monkeypatch):
    """The guard that stops a stray run paying for hundreds of CVs."""
    monkeypatch.setattr("builtins.input", lambda _: "n")

    recorder = run(total=4, argv=[])

    assert recorder.prompted == []


def test_a_yes_generates(run):
    recorder = run(total=4, argv=["--yes"])

    assert len(recorder.prompted) == 4


def test_the_limit_caps_how_many_are_generated(run):
    recorder = run(total=4, argv=["--yes", "--limit", "2"])

    assert len(recorder.prompted) == 2


def test_a_limit_larger_than_the_work_generates_everything(run):
    recorder = run(total=4, argv=["--yes", "--limit", "99"])

    assert len(recorder.prompted) == 4


def test_the_prompt_states_the_count_and_the_cost(capsys):
    answers = []
    generate_cvs.confirm(177, ask=lambda prompt: answers.append(prompt) or "n")

    printed = capsys.readouterr().out
    assert "177 CVs to generate" in printed
    assert "177 Claude calls" in printed
    assert "$1.0" in printed


def test_only_a_yes_proceeds():
    assert generate_cvs.confirm(1, ask=lambda _: "y") is True
    assert generate_cvs.confirm(1, ask=lambda _: "Y") is True
    assert generate_cvs.confirm(1, ask=lambda _: "") is False
    assert generate_cvs.confirm(1, ask=lambda _: "n") is False
    assert generate_cvs.confirm(1, ask=lambda _: "yes please") is False


def test_a_dataset_already_complete_asks_nothing(run, capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "y")
    run(total=4, argv=["--yes"])

    recorder = run(total=4, argv=[])

    assert recorder.prompted == []
    assert "Nothing to generate" in capsys.readouterr().out


def test_pending_ignores_cvs_already_in_the_ground_truth():
    specs = [
        {"id": "001", "folder": "legitimate"},
        {"id": "002", "folder": "legitimate"},
    ]
    assert generate_cvs.pending(specs, {"001", "002"}) == []
