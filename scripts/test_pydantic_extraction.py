"""
Test that Pydantic validation works on a real Claude extraction.

Picks one PDF from GCS, runs through extraction, validates with Pydantic.
Does NOT write to BigQuery. Just prints the result.
"""
import sys
import os
from dotenv import load_dotenv

# Add project root to path so we can import dagster.assets
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

load_dotenv()

from google.cloud import storage
import fitz
from orchestration.assets.extraction import extract_cv_data_with_claude
from orchestration.assets.schemas import ExtractedCV
from pydantic import ValidationError


def main():
    # Pick a CV to test
    bucket_name = os.getenv("GCS_BUCKET_NAME")
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    
    blobs = list(bucket.list_blobs(prefix="cvs/raw/legitimate/"))
    pdfs = [b for b in blobs if b.name.endswith(".pdf")]
    
    if not pdfs:
        print("No PDFs found")
        return
    
    test_blob = pdfs[0]
    print(f"Testing with: {test_blob.name}")
    
    # Extract text
    pdf_bytes = test_blob.download_as_bytes()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    raw_text = ""
    for page in doc:
        raw_text += page.get_text()
    doc.close()
    
    print(f"Raw text length: {len(raw_text)} chars")
    print("Calling Claude...")
    
    # Run extraction
    try:
        result = extract_cv_data_with_claude(raw_text)
        
        assert isinstance(result, ExtractedCV), f"Expected ExtractedCV, got {type(result)}"
        assert result.candidate_name, "candidate_name is empty"
        assert len(result.work_experience) > 0, "no work experience extracted"
        
        print(f"✓ {test_blob.name}: {result.candidate_name}, "
            f"{len(result.work_experience)} jobs, {len(result.skills)} skills")
    
    except ValidationError as e:
        print(f"Pydantic validation failed:")
        print(e.json(indent=2))
    
    except Exception as e:
        print(f"Other error: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()