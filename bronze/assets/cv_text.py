"""
GCS PDFs -> bronze.raw_cv_texts.

Reads each PDF, extracts its text with PyMuPDF, labels it, and archives
the raw JSON to GCS before loading. Skips CVs whose content hash is
unchanged since the last run.
"""

import os
from datetime import datetime, timezone

import fitz
from dagster import asset, get_dagster_logger
from dotenv import load_dotenv
from pydantic import ValidationError

from bronze.rules.parsing import (
    categorize_skill,
    classify_profile,
    compute_file_hash,
    detect_seniority,
)
from bronze.storage import (
    download_pdf_from_gcs,
    list_pdfs_in_gcs,
    save_json_to_gcs,
)
from bronze.warehouse import (
    BRONZE_DATASET,
    PROJECT_ID,
    delete_cv_data,
    get_all_cv_texts,
    get_processed_submission_ids,
    get_processed_versions,
    insert_rows_to_bigquery,
)

load_dotenv()

# ── ASSET 1: extract_raw_text ─────────────────────────────────────────────
@asset
def extract_raw_text():
    """
    Reads each PDF from GCS.
    Extracts raw text with PyMuPDF.
    Classifies profile type and detects seniority.
    Saves raw text JSON to GCS.
    Loads into BigQuery Bronze raw_candidates table.
    """
    log = get_dagster_logger()
    results = []
    
    # Now returns dict: {submission_id: content_hash}
    existing = get_processed_versions("raw_cv_texts")
    log.info(f"Already processed: {len(existing)} CVs")
    
    for folder in ["inconsistent", "legitimate"]:
        blobs = list_pdfs_in_gcs(folder)
        
        for blob in blobs:
            filename = blob.name.split("/")[-1]
            submission_id = filename.replace(".pdf", "")
            
            try:
                pdf_bytes = download_pdf_from_gcs(blob)
                current_hash = compute_file_hash(pdf_bytes)
                
                # Three cases
                if submission_id in existing:
                    if existing[submission_id] == current_hash:
                        # Unchanged: skip
                        log.info(f"[SKIP unchanged] {submission_id}")
                        continue
                    else:
                        # Changed: delete old, then reprocess
                        log.info(f"[REPROCESS changed] {submission_id}")
                        delete_cv_data(submission_id)
                
                # Process (new or changed)
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                raw_text = ""
                for page in doc:
                    raw_text += page.get_text()
                doc.close()
                
                if not raw_text.strip():
                    log.warning(f"Empty text: {filename}")
                    continue
                
                profile_type = classify_profile(raw_text)
                
                row = {
                    "submission_id": submission_id,
                    "content_hash": current_hash,  # new field
                    "profile_type": profile_type,
                    "cv_file_path": f"gs://{BUCKET_NAME}/{blob.name}",
                    "submission_timestamp": datetime.now(timezone.utc).isoformat(),
                    "raw_text": raw_text,
                    "folder": folder,
                }
                results.append(row)
                log.info(f"[OK] {submission_id}")
                
            except Exception as e:
                log.error(f"[FAIL] {filename}: {e}")
    
    if results:
        table_id = f"{PROJECT_ID}.{BRONZE_DATASET}.raw_cv_texts"
        insert_rows_to_bigquery(table_id, results)
        log.info(f"Inserted {len(results)} rows")
    
    return results
# ── ASSET 2: extract_entities (LLM Extraction) ─────────────────────────────────
