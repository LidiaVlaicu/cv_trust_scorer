# tools/

Things you run **by hand**, when setting the project up or when something is
broken. They print for a person to read; they are not part of the pipeline and
not part of the test suite.

| Tool | Use it when |
|---|---|
| `check_gcp_auth.py` | Credentials just changed, or the pipeline is failing with permission errors. Exits non-zero if you are authenticated as a human rather than the service account. |
| `check_cv_extraction.py` | A prompt or model changed and you want to know whether extraction still produces the shape bronze expects. One Claude call, one PDF, nothing written. |
| `lookup_company.py` | A company from a CV is not matching, and you want to see whether Companies House knows it at all. `python tools/lookup_company.py "TechVault Solutions Ltd"` |

## Why these are not in `tests/`

They were once named `test_auth.py`, `test_company_house_api.py` and so on,
which made them look like part of the suite. They are the opposite of it:

| | `tests/` | `tools/` |
|---|---|---|
| Checks itself | yes, every assertion | no, a person reads the output |
| Needs credentials | never | always |
| Costs money | no | yes - Claude and API calls |
| Runs in CI | every commit | never |
| Runtime | ~1s for all 234 | seconds to minutes each |

A test that needs a network, a credential and a human to interpret it is not a
test. Keeping the two kinds apart means `pytest` stays fast and free to run,
and nothing in CI depends on a service being up.

## Deleted

`test_company_house_ingestion.py` was removed in the same change. It was
seventeen lines hardcoded to one company name that called the real ingestion -
silently writing rows into BigQuery - and then printed `"Done."`. To look a
company up without side effects, use `lookup_company.py`; to actually ingest,
materialize the asset. It is in git history if it is ever wanted back.
