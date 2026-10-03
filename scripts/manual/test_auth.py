"""
Verifies that GCP authentication is correctly configured for impersonation.

Run after setting up authentication or when debugging auth issues:
    python scripts/verify_auth.py
"""
from google.cloud import bigquery
from google.auth import default
from google.auth.transport.requests import Request
import sys
from datetime import datetime, timezone


def main():
    # Note: scopes must be specified explicitly for impersonated credentials
    # to work correctly with the refresh flow. See:
    # https://github.com/googleapis/google-auth-library-python/issues/...
    credentials, project = default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(Request())
    
    creds_type = type(credentials).__name__
    print(f"Credentials type: {creds_type}")
    
    if hasattr(credentials, 'service_account_email'):
        print(f"Service account: {credentials.service_account_email}")
    
    if hasattr(credentials, 'expiry') and credentials.expiry:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        lifetime_seconds = (credentials.expiry - now).total_seconds()
        print(f"Token expires at: {credentials.expiry} UTC")
        print(f"Token lifetime: {lifetime_seconds/60:.1f} minutes")
    
    client = bigquery.Client()
    print(f"Project: {client.project}")
    
    result = list(client.query("SELECT SESSION_USER() AS who").result())
    auth_principal = result[0].who
    print(f"Authenticated as: {auth_principal}")
    
    if "gserviceaccount.com" not in auth_principal:
        print(f"\nWARNING: Authenticated as a human account, not a service account.")
        sys.exit(1)
    
    print("\nAuthentication is correctly configured.")


if __name__ == "__main__":
    main()