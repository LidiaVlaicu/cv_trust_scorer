from dagster import (
    Definitions,
    load_asset_checks_from_modules,
    load_assets_from_modules,
)

from gold.assets import (
    signal_company_verification,
    signal_responsibility_mismatch,
    signal_timeline_consistency,
)
from bronze.assets import check_assets, extract_cv_text, extract_entities
from silver.assets import (
    silver_candidates,
    silver_skills,
    silver_work_experience,
)

asset_modules = [
    extract_cv_text,
    extract_entities,
    signal_company_verification,
    silver_candidates,
    silver_skills,
    silver_work_experience,
    signal_timeline_consistency,
    signal_responsibility_mismatch,
]

all_assets = load_assets_from_modules(asset_modules)

# Data-quality checks on the bronze tables. They run after the asset that
# writes each table; the blocking ones stop the run so silver never consumes
# bronze with broken keys.
all_asset_checks = load_asset_checks_from_modules([check_assets])

defs = Definitions(
    assets=all_assets,
    asset_checks=all_asset_checks,
)
