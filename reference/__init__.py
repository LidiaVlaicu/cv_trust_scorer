"""
Human-reviewed reference data: the inputs the pipeline compares against.

Nothing here is derived from the CVs. These are the taxonomies and ladders a
person has read and signed off, loaded into BigQuery as `dim_*` tables so a
correction is a data change rather than a code change.

    reviewed/   the CSVs a person reviews and edits
    parsing/    pure parsers that turn those CSVs into rows, with validation
    loaders/    thin I/O shells that replace each dim_ table (full refresh)

`seniority_ladder` is the exception: it is reference data that lives in code
rather than a CSV, because it is a published ladder with a citation rather
than a list that grows as new CVs arrive.
"""

from pathlib import Path

# The reviewed CSVs. Both the loaders and the tests that assert against the
# real files resolve them from here, so the location is defined exactly once.
REVIEWED_DIR = Path(__file__).resolve().parent / "reviewed"

SKILLS_TAXONOMY_CSV = REVIEWED_DIR / "skills_taxonomy_review.csv"
JOB_TITLES_CSV = REVIEWED_DIR / "job_titles_review.csv"
LOCATION_ALIASES_CSV = REVIEWED_DIR / "location_aliases_review.csv"
DATES_CSV = REVIEWED_DIR / "dates_review.csv"
