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

    client.create_table(table, exists_ok=True)

    print(f"Created {table_id}")


if __name__ == "__main__":
    create_table()