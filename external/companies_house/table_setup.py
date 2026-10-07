import os

from google.cloud import bigquery
from dotenv import load_dotenv

load_dotenv()


def create_table() -> None:
    client = bigquery.Client(project=os.getenv("GCP_PROJECT_ID"))

    dataset = os.getenv("BQ_DATASET_BRONZE")

    table_id = (
        f"{client.project}.{dataset}.companies_house_search_results"
    )

    schema = [
        bigquery.SchemaField(
            "company_query",
            "STRING",
            mode="REQUIRED",
        ),
        bigquery.SchemaField(
            "company_query_normalized",
            "STRING",
        ),
        bigquery.SchemaField(
            "company_number",
            "STRING",
        ),
        bigquery.SchemaField(
            "company_name",
            "STRING",
        ),
        bigquery.SchemaField(
            "company_status",
            "STRING",
        ),
        bigquery.SchemaField(
            "company_type",
            "STRING",
        ),
        bigquery.SchemaField(
            "address_snippet",
            "STRING",
        ),
        bigquery.SchemaField(
            "retrieved_at",
            "TIMESTAMP",
            mode="REQUIRED",
        ),
    ]

    table = bigquery.Table(table_id, schema=schema)

    try:
        existing = client.get_table(table_id)
    except Exception:
        client.create_table(table)
        print(f"Created {table_id}")
        return

    # Table already exists (e.g. from an earlier manual test) — add any new
    # nullable columns without touching existing data.
    existing_names = {field.name for field in existing.schema}
    new_fields = [field for field in schema if field.name not in existing_names]
    if new_fields:
        existing.schema = list(existing.schema) + new_fields
        client.update_table(existing, ["schema"])
        print(f"Updated {table_id} with columns: {[f.name for f in new_fields]}")
    else:
        print(f"{table_id} already up to date")


def create_verification_signal_table() -> None:
    client = bigquery.Client(project=os.getenv("GCP_PROJECT_ID"))

    dataset = os.getenv("BQ_DATASET_GOLD")

    table_id = (
        f"{client.project}.{dataset}.signal_company_verification"
    )

    schema = [
        bigquery.SchemaField("submission_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("experience_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("company_name_cv", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("matched_company_number", "STRING"),
        bigquery.SchemaField("matched_company_name", "STRING"),
        bigquery.SchemaField("status", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("verified_at", "TIMESTAMP", mode="REQUIRED"),
    ]

    table = bigquery.Table(table_id, schema=schema)

    client.create_table(table, exists_ok=True)

    print(f"Created {table_id}")


if __name__ == "__main__":
    create_table()
    create_verification_signal_table()