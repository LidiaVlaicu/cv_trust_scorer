from dagster import Definitions, load_assets_from_modules

from gold.assets import (
    company_verification,
    responsibility_mismatch,
    timeline_consistency,
)
from orchestration.assets import extraction
from silver.assets import (
    candidates,
    skills,
    work_experience,
)

all_assets = load_assets_from_modules([
    extraction,
    company_verification,
    candidates,
    skills,
    work_experience,
    timeline_consistency,
    responsibility_mismatch,
])

defs = Definitions(
    assets=all_assets
)
