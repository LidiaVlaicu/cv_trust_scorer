from dagster import Definitions, load_assets_from_modules

from gold.assets import (
    company_verification,
    responsibility_mismatch,
    timeline_consistency,
)
from orchestration.assets import (
    extraction,
    silver,
    silver_skills,
    silver_work_experience,
)

all_assets = load_assets_from_modules([
    extraction,
    company_verification,
    silver,
    silver_skills,
    silver_work_experience,
    timeline_consistency,
    responsibility_mismatch,
])

defs = Definitions(
    assets=all_assets
)
