from dagster import Definitions, load_assets_from_modules
import sys
import os

sys.path.append(os.path.dirname(__file__))

from assets import extraction

all_assets = load_assets_from_modules([extraction])

defs = Definitions(assets=all_assets)
