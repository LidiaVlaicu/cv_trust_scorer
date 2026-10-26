"""
Tests that the Dagster definitions load and hold what the pipeline expects.

Nothing here runs an asset. It checks the wiring: a duplicate asset key, a
renamed asset a check still points at, or an import that stopped resolving
all fail when Dagster builds the repository, and would otherwise only show
up when starting the UI.
"""

from dagster import Definitions

from pipeline.definitions import defs

EXPECTED_ASSETS = {
    "extract_raw_text",
    "extract_entities",
    "silver_candidates",
    "silver_skills",
    "silver_work_experience",
    "signal_timeline_consistency",
    "signal_responsibility_mismatch",
    "verify_companies",
}


def repository():
    return defs.get_repository_def()


def test_the_definitions_are_loadable():
    """Fails on a duplicate key or an unresolved dependency."""
    Definitions.validate_loadable(defs)


def test_every_layer_contributes_its_assets():
    loaded = {key.to_user_string() for key in repository().assets_defs_by_key}

    assert loaded == EXPECTED_ASSETS


def test_the_bronze_checks_are_registered():
    """The blocking ones are what stop silver consuming broken bronze."""
    assert list(defs.asset_checks)


def test_every_check_points_at_an_asset_that_exists():
    loaded = {key.to_user_string() for key in repository().assets_defs_by_key}

    for checks_def in defs.asset_checks:
        for spec in checks_def.check_specs:
            assert spec.asset_key.to_user_string() in loaded
