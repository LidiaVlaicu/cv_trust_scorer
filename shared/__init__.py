"""
Shared BigQuery plumbing for the layer adapters.

Every layer talks to the warehouse through its own adapter - the only code
allowed to import `google.cloud` - and those adapters were each repeating the
same few things: build a client from GCP_PROJECT_ID, resolve a dataset name
from the environment, join project.dataset.table, create a table if it is
missing, and replace a table wholesale from a list of dicts.

Used by every layer: bronze and the company signal for `ensure_table`, since
they append and so are not created by the write itself; silver, gold and
reference for `replace_table`, which creates the table as it loads.

This module is deliberately thin. It is a place for the repetition, not an
abstraction over BigQuery: adapters still write their own queries, own their
schemas, and decide what to read. Anything that only one adapter needs stays
in that adapter.
"""

from shared.bigquery_client import bigquery_client, dataset_name
from shared.bigquery_tables import ensure_table, replace_table, table_id

__all__ = [
    "bigquery_client",
    "dataset_name",
    "ensure_table",
    "replace_table",
    "table_id",
]
