"""
Tests for the Dagster wrappers around each run_* function.

Every asset is the same three lines: build the warehouse adapter, call the
pure runner, report through the Dagster logger. The runners are tested in
their own suites; what is checked here is the wiring, which is the part a
refactor silently breaks - a wrapper left pointing at the wrong adapter, or
no longer returning the summary Dagster shows in the UI.
"""

import pytest

from bronze.assets import extract_cv_text, extract_entities
from gold.assets import (
    signal_company_verification,
    signal_responsibility_mismatch,
    signal_timeline_consistency,
)
from silver.assets import silver_candidates, silver_skills, silver_work_experience

SUMMARY = {"rows": 3}

# module, the asset function, the adapter it must build, the runner it calls
ASSETS = [
    (
        extract_cv_text,
        "extract_raw_text",
        "GcsBigQueryCvTextStore",
        "run_extract_raw_text",
    ),
    (
        extract_entities,
        "extract_entities",
        "BigQueryEntitiesStore",
        "run_extract_entities",
    ),
    (
        silver_candidates,
        "silver_candidates",
        "BigQueryCandidatesWarehouse",
        "run_silver_candidates",
    ),
    (silver_skills, "silver_skills", "BigQuerySkillsWarehouse", "run_silver_skills"),
    (
        silver_work_experience,
        "silver_work_experience",
        "BigQueryWorkExperienceWarehouse",
        "run_silver_work_experience",
    ),
    (
        signal_timeline_consistency,
        "signal_timeline_consistency",
        "BigQueryTimelineWarehouse",
        "run_signal_timeline_consistency",
    ),
    (
        signal_responsibility_mismatch,
        "signal_responsibility_mismatch",
        "BigQueryResponsibilityWarehouse",
        "run_signal_responsibility_mismatch",
    ),
    (
        signal_company_verification,
        "verify_companies",
        "CompanyHouseStorage",
        "run_verify_companies",
    ),
]

IDS = [asset for _, asset, _, _ in ASSETS]


@pytest.fixture
def invoke(monkeypatch):
    """Calls an asset with its adapter and runner replaced, returning both."""

    def go(module, asset, adapter_name, runner_name):
        built = []
        called = []

        monkeypatch.setattr(
            module, adapter_name, lambda *a, **kw: built.append(kw) or "adapter"
        )

        def runner(store, **kwargs):
            called.append((store, kwargs))
            return SUMMARY

        monkeypatch.setattr(module, runner_name, runner)
        returned = getattr(module, asset)()
        return returned, built, called

    return go


@pytest.mark.parametrize("module,asset,adapter,runner", ASSETS, ids=IDS)
def test_each_asset_returns_the_summary_dagster_shows(
    invoke, module, asset, adapter, runner
):
    returned, _, _ = invoke(module, asset, adapter, runner)

    assert returned.items() >= SUMMARY.items()


@pytest.mark.parametrize("module,asset,adapter,runner", ASSETS, ids=IDS)
def test_each_asset_records_how_long_it_took(invoke, module, asset, adapter, runner):
    """The summary is what Dagster shows, so the duration travels with it."""
    returned, _, _ = invoke(module, asset, adapter, runner)

    assert isinstance(returned["duration_seconds"], float)
    assert returned["duration_seconds"] >= 0


@pytest.mark.parametrize("module,asset,adapter,runner", ASSETS, ids=IDS)
def test_each_asset_runs_against_the_adapter_it_builds(
    invoke, module, asset, adapter, runner
):
    _, built, called = invoke(module, asset, adapter, runner)

    assert len(built) == 1
    store, _ = called[0]
    assert store == "adapter"


@pytest.mark.parametrize("module,asset,adapter,runner", ASSETS, ids=IDS)
def test_each_asset_reports_through_the_dagster_logger(
    invoke, module, asset, adapter, runner
):
    """Without this the run log is empty and a skipped CV is invisible."""
    _, _, called = invoke(module, asset, adapter, runner)

    _, kwargs = called[0]
    assert callable(kwargs["report"])


def test_the_company_signal_hands_its_schema_to_the_store(invoke):
    """The store creates the signal table, so the gold asset owns the schema."""
    _, built, _ = invoke(
        signal_company_verification,
        "verify_companies",
        "CompanyHouseStorage",
        "run_verify_companies",
    )

    assert built[0]["verification_schema"] is signal_company_verification.SIGNAL_SCHEMA
