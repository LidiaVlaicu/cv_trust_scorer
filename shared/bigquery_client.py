"""Constructing a BigQuery client and resolving dataset names from the env."""

import os

from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()

# Layer name -> the environment variable holding that layer's dataset.
_DATASET_ENV = {
    "bronze": "BQ_DATASET_BRONZE",
    "silver": "BQ_DATASET_SILVER",
    "gold": "BQ_DATASET_GOLD",
}


def bigquery_client(client: bigquery.Client | None = None) -> bigquery.Client:
    """
    `client` if one was injected, otherwise a client for GCP_PROJECT_ID.

    Adapters take an optional client so a test or a notebook can supply its
    own; this keeps that one-line default in a single place.
    """
    if client is not None:
        return client
    return bigquery.Client(project=os.getenv("GCP_PROJECT_ID"))


def dataset_name(layer: str, override: str | None = None) -> str:
    """
    The dataset for a medallion layer, or `override` when given.

    Raises rather than returning None: a missing dataset variable otherwise
    surfaces much later as a query against `project.None.some_table`.
    """
    if override is not None:
        return override
    try:
        variable = _DATASET_ENV[layer]
    except KeyError:
        raise ValueError(
            f"unknown layer {layer!r}; expected one of {sorted(_DATASET_ENV)}"
        ) from None
    value = os.getenv(variable)
    if not value:
        raise RuntimeError(f"Missing required env var: {variable}")
    return value
