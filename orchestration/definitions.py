from dagster import Definitions, load_assets_from_modules

from .assets import extraction

all_assets = load_assets_from_modules([extraction])

defs = Definitions(
    assets=all_assets
)