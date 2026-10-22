"""
Tests for the asset timer.

It wraps the work rather than living inside it, so the summary the runner
returns is passed through untouched apart from the duration added to it.
"""

from shared.timing import timed


def test_the_summary_from_the_work_is_returned():
    reported = []

    result = timed("silver_candidates", reported.append, lambda: {"rows": 3})

    assert result["rows"] == 3


def test_a_duration_is_added_to_the_summary():
    result = timed("silver_candidates", lambda m: None, lambda: {})

    assert isinstance(result["duration_seconds"], float)
    assert result["duration_seconds"] >= 0


def test_the_duration_is_reported_under_the_asset_name():
    reported = []

    timed("signal_timeline_consistency", reported.append, lambda: {})

    assert reported[0].startswith("signal_timeline_consistency finished in ")


def test_the_work_runs_exactly_once():
    runs = []

    timed("x", lambda m: None, lambda: runs.append(1) or {})

    assert runs == [1]


def test_a_failing_asset_is_not_reported_as_finished():
    """A duration on a crashed run would read as a successful one."""
    reported = []

    try:
        timed("x", reported.append, lambda: (_ for _ in ()).throw(RuntimeError("x")))
    except RuntimeError:
        pass

    assert reported == []
