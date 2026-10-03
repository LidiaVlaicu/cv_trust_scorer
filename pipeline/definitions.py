from dagster import (
    Definitions,
    load_asset_checks_from_modules,
    load_assets_from_modules,
)

from gold.assets import (
    company_verification,
    responsibility_mismatch,
    timeline_consistency,
)
from bronze.assets import extract_cv_text, extract_entities, quality
from silver.assets import (
    candidates,
    skills,
    work_experience,
)

asset_modules = [
    extract_cv_text,
    extract_entities,
    company_verification,
    candidates,
    skills,
    work_experience,
    timeline_consistency,
    responsibility_mismatch,
]

all_assets = load_assets_from_modules(asset_modules)

# Data-quality checks on the bronze tables. They run after the asset that
# writes each table; the blocking ones stop the run so silver never consumes
# bronze with broken keys.
all_asset_checks = load_asset_checks_from_modules([quality])

defs = Definitions(
    assets=all_assets,
    asset_checks=all_asset_checks,
)
