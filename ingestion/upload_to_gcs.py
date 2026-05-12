import os
from pathlib import Path
from dotenv import load_dotenv
from google.cloud import storage

load_dotenv()

# ── Configuration ─────────────────────────────────────────────────────────
BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")

# ── Upload function ───────────────────────────────────────────────────────
def upload_cvs_to_gcs():
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)

    uploaded = 0
    skipped = 0
    failed = 0

    for folder in ["inconsistent", "legitimate"]:
        local_folder = Path(f"data/{folder}")

        if not local_folder.exists():
            print(f"[WARN] Folder not found: {local_folder}")
            continue

        pdfs = list(local_folder.glob("*.pdf"))
        print(f"\nUploading {len(pdfs)} CVs from data/{folder}/...")

        for pdf_path in sorted(pdfs):
            # destination path in GCS
            gcs_path = f"cvs/raw/{folder}/{pdf_path.name}"
            blob = bucket.blob(gcs_path)

            # skip if already uploaded
            if blob.exists():
                skipped += 1
                continue

            try:
                blob.upload_from_filename(str(pdf_path))
                print(f"  [OK] {pdf_path.name}")
                uploaded += 1
            except Exception as e:
                print(f"  [FAIL] {pdf_path.name}: {e}")
                failed += 1

    # also upload ground truth CSV
    ground_truth_path = Path("data/ground_truth.csv")
    if ground_truth_path.exists():
        blob = bucket.blob("cvs/raw/ground_truth.csv")
        if not blob.exists():
            blob.upload_from_filename(str(ground_truth_path))
            print(f"\n  [OK] ground_truth.csv uploaded")
        else:
            print(f"\n  [SKIP] ground_truth.csv already exists")

    print(f"\nDone.")
    print(f"Uploaded: {uploaded} | Skipped: {skipped} | Failed: {failed}")

    print(f"\nGCS structure:")
    print(f"gs://{BUCKET_NAME}/cvs/raw/inconsistent/  ({sum(1 for _ in Path('data/inconsistent').glob('*.pdf') if Path('data/inconsistent').exists())} files)")
    print(f"gs://{BUCKET_NAME}/cvs/raw/legitimate/    ({sum(1 for _ in Path('data/legitimate').glob('*.pdf') if Path('data/legitimate').exists())} files)")
    print(f"gs://{BUCKET_NAME}/cvs/raw/ground_truth.csv")

if __name__ == "__main__":
    if not BUCKET_NAME:
        print("ERROR: GCS_BUCKET_NAME not set in .env file")
        print("Add this to your .env file:")
        print("GCS_BUCKET_NAME=your-bucket-name")
        exit(1)

    print(f"Uploading CVs to bucket: {BUCKET_NAME}")
    upload_cvs_to_gcs()
