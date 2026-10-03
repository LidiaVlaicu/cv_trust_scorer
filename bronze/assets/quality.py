import os
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()
PROJECT_ID = os.getenv("GCS_PROJECT_ID")
client = bigquery.Client(project=PROJECT_ID)
BRONZE_DATASET = os.getenv("BQ_DATASET_BRONZE")

def check_nulls_and_empty(dataset, table):
    schema_query = f"""
        SELECT column_name, data_type
        FROM {dataset}.INFORMATION_SCHEMA.COLUMNS
        WHERE table_name = '{table}'
        ORDER BY ordinal_position
    """
    columns = list(client.query(schema_query).result())

    checks = []
    for col in columns:
        name = col.column_name
        dtype = col.data_type

        if dtype == "STRING":
            check = f"COUNTIF({name} IS NULL OR {name} = '') as empty_{name}"
        else:
            check = f"COUNTIF({name} IS NULL) as null_{name}"
        
        checks.append(check)

    query = f"""
        SELECT COUNT(*) as total_rows, {', '.join(checks)}
        FROM `{PROJECT_ID}.{dataset}.{table}`
    """

    results = list(client.query(query).result())
    row = results[0]

    print(f"\n=== NULL + EMPTY CHECK: {table} ===")
    print(f"Total rows: {row['total_rows']}")
    print()
    
    for col in columns:
        name = col.column_name
        
        if col.data_type == "STRING":
            key = f"empty_{name}"
        else:
            key = f"null_{name}"
        
        count = row[key]
        
        if row['total_rows'] > 0:
            pct = count / row['total_rows'] * 100
        else:
            pct = 0
        
        if count == 0:
            status = "✅"
        else:
            status = "⚠️"
        
        print(f"{status} {name}: {count} missing ({pct:.1f}%)")
    
check_nulls_and_empty(BRONZE_DATASET, "raw_candidates")
check_nulls_and_empty(BRONZE_DATASET, "raw_work_experience")
check_nulls_and_empty(BRONZE_DATASET, "raw_skills")