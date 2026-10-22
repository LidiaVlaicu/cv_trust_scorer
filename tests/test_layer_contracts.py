"""
Enforces the column contract between the layers.

Each adapter names the columns it reads in SQL, and each table declares the
columns it writes as a BigQuery schema. Nothing connects the two: rename a
column in a silver schema and the gold query that selects it keeps parsing
fine, then fails at run time against the warehouse.

These tests read the SELECT list out of every cross-layer query and check it
against the schema of the table it reads from, so a rename breaks the build
instead of the pipeline.
"""

import re

import pytest

from bronze.assets.extract_cv_text import CV_TEXTS_SCHEMA
from bronze.assets.extract_entities import SCHEMAS as BRONZE_ENTITY_SCHEMAS
from gold.assets.signal_responsibility_mismatch import BigQueryResponsibilityWarehouse
from gold.assets.signal_timeline_consistency import BigQueryTimelineWarehouse
from reference.loaders.load_dim_job_titles import DIM_JOB_TITLES_SCHEMA
from reference.loaders.load_dim_location_aliases import DIM_LOCATION_ALIASES_SCHEMA
from reference.loaders.load_dim_skills import DIM_SKILLS_SCHEMA
from silver.assets.silver_candidates import (
    SILVER_CANDIDATES_SCHEMA,
    BigQueryCandidatesWarehouse,
)
from silver.assets.silver_skills import SILVER_SKILLS_SCHEMA, BigQuerySkillsWarehouse
from silver.assets.silver_work_experience import (
    SILVER_WORK_EXPERIENCE_SCHEMA,
    BigQueryWorkExperienceWarehouse,
)

# Every table the pipeline reads from, and the schema that declares it.
COLUMNS_BY_TABLE = {
    "raw_cv_texts": CV_TEXTS_SCHEMA,
    "raw_candidates": BRONZE_ENTITY_SCHEMAS["raw_candidates"],
    "raw_work_experience": BRONZE_ENTITY_SCHEMAS["raw_work_experience"],
    "raw_skills": BRONZE_ENTITY_SCHEMAS["raw_skills"],
    "silver_candidates": SILVER_CANDIDATES_SCHEMA,
    "silver_work_experience": SILVER_WORK_EXPERIENCE_SCHEMA,
    "silver_skills": SILVER_SKILLS_SCHEMA,
    "dim_job_titles": DIM_JOB_TITLES_SCHEMA,
    "dim_location_aliases": DIM_LOCATION_ALIASES_SCHEMA,
    "dim_skills": DIM_SKILLS_SCHEMA,
}


class RecordingClient:
    """A BigQuery client that records queries instead of running them."""

    project = "a-project"

    def __init__(self):
        self.queries: list[str] = []

    def query(self, query, job_config=None):
        self.queries.append(query)
        return self

    def result(self):
        return []


def queries_made_by(warehouse_class, reader_names: list[str]) -> list[str]:
    """Every SQL string the named reader methods send."""
    client = RecordingClient()
    warehouse = warehouse_class(client=client)
    for name in reader_names:
        getattr(warehouse, name)()
    return client.queries


def selected_columns(query: str) -> set[str]:
    """The bare column names in the SELECT list of a single-table query."""
    select_list = re.search(r"SELECT\s+(.*?)\s+FROM", query, re.S | re.I).group(1)
    return {part.strip() for part in select_list.split(",") if part.strip()}


def table_read_by(query: str) -> str:
    """The unqualified name of the table the query reads from."""
    reference = re.search(r"FROM\s+`([^`]+)`", query, re.I).group(1)
    return reference.split(".")[-1]


READERS = [
    (BigQueryCandidatesWarehouse, ["read_raw_candidates"]),
    (
        BigQueryWorkExperienceWarehouse,
        ["read_job_titles", "read_location_aliases", "read_raw_work_experience"],
    ),
    (BigQuerySkillsWarehouse, ["read_taxonomy", "read_raw_skills"]),
    (BigQueryTimelineWarehouse, ["read_work_experience"]),
    (BigQueryResponsibilityWarehouse, ["read_work_experience"]),
]

ALL_QUERIES = [
    query
    for warehouse_class, readers in READERS
    for query in queries_made_by(warehouse_class, readers)
]


@pytest.mark.parametrize("query", ALL_QUERIES, ids=table_read_by)
def test_every_column_read_exists_in_the_table_it_is_read_from(query):
    """
    If this fails, a schema and a query that reads it have drifted apart.

    Renaming a column in a silver schema without updating the gold query
    that selects it is the case this exists to catch.
    """
    table = table_read_by(query)
    declared = {field.name for field in COLUMNS_BY_TABLE[table]}

    missing = selected_columns(query) - declared

    assert not missing, (
        f"query against {table} selects {sorted(missing)}, "
        f"which {table} does not declare. Declared: {sorted(declared)}"
    )


def test_every_table_read_is_one_the_pipeline_declares():
    """Guards the test above from passing because a table was never checked."""
    for query in ALL_QUERIES:
        assert table_read_by(query) in COLUMNS_BY_TABLE


def test_there_are_queries_to_check():
    """Guards against the parametrized suite silently finding nothing."""
    assert len(ALL_QUERIES) >= 8
