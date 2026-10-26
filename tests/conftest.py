"""
Fake environment values for the variables read at import time.

A few adapters read `os.environ` when the module is first imported, so
importing a test that touches them fails before any test runs unless those
variables are set. The values here are placeholders: no test reaches GCS or
BigQuery, and `setdefault` leaves a real environment alone.
"""

import os

PLACEHOLDER_ENV = {
    "GCP_PROJECT_ID": "test-project",
    "GCP_LOCATION": "europe-west1",
    "GCS_BUCKET_NAME": "test-bucket",
    "BQ_DATASET_BRONZE": "bronze",
    "BQ_DATASET_SILVER": "silver",
    "BQ_DATASET_GOLD": "gold",
    "ANTHROPIC_API_KEY": "test-key",
    "COMPANIES_HOUSE_API_KEY": "test-key",
}

for name, value in PLACEHOLDER_ENV.items():
    os.environ.setdefault(name, value)
