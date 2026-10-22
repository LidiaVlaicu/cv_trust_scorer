"""Addressing and replacing BigQuery tables."""

from google.cloud import bigquery


def table_id(client: bigquery.Client, dataset: str, table: str) -> str:
    """Fully qualified `project.dataset.table`."""
    return f"{client.project}.{dataset}.{table}"


def ensure_table(
    client: bigquery.Client,
    table: str,
    schema: list[bigquery.SchemaField],
) -> None:
    """
    Create `table` with `schema` if it does not exist; a no-op when it does,
    and it never alters an existing table.

    Needed only by the tables that are appended to - the bronze raw tables and
    the company signal. A table written with `replace_table` is created by the
    load job itself.
    """
    client.create_table(bigquery.Table(table, schema=schema), exists_ok=True)


def replace_table(
    client: bigquery.Client,
    table: str,
    rows: list[dict],
    schema: list[bigquery.SchemaField],
) -> None:
    """
    Replace `table` with `rows` in one load job (WRITE_TRUNCATE).

    Full refresh is the right default across these layers: silver and gold are
    pure functions of the layer beneath them, so they are recomputed rather
    than accumulated, and truncating keeps a re-run from doubling the rows.
    """
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition="WRITE_TRUNCATE",
    )
    client.load_table_from_json(rows, table, job_config=job_config).result()
