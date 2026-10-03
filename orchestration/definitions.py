from dagster import Definitions, load_assets_from_modules

from .assets import (
    extraction,
    signal_responsibility_mismatch,
    signal_timeline_consistency,
    silver,
    silver_skills,
    silver_work_experience,
    verification,
)

all_assets = load_assets_from_modules([
    extraction,
    verification,
    silver,
    silver_skills,
    silver_work_experience,
    signal_timeline_consistency,
    signal_responsibility_mismatch,
])

defs = Definitions(
    assets=all_assets
)