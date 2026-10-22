"""
How long an asset took, recorded where the orchestrator can see it.

Timing belongs to the shell rather than the rules: the `run_*` functions
stay free of the wall clock, so their tests remain deterministic, and the
Dagster wrapper around each one measures it instead. The duration is both
logged and returned, so it appears in the run log and in the asset's
materialization metadata.
"""

from time import perf_counter
from typing import Callable


def timed(label: str, report: Callable[[str], None], work: Callable[[], dict]) -> dict:
    """Runs `work`, reports how long it took, and adds it to the summary."""
    started = perf_counter()
    summary = work()
    seconds = round(perf_counter() - started, 2)
    report(f"{label} finished in {seconds}s")
    return {**summary, "duration_seconds": seconds}
