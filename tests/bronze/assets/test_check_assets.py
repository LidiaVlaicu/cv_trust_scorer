"""
Tests for the result builder the four bronze data-quality checks share.

It turns {problem: rows affected} into an AssetCheckResult, and decides
whether the check passed. The queries around it need the warehouse; this
part does not.
"""

import pytest
from dagster import AssetCheckSeverity

from bronze.assets import check_assets
from bronze.assets.check_assets import _result, _table


def test_no_failures_passes():
    result = _result({}, severity=AssetCheckSeverity.ERROR, subject="raw_cv_texts")

    assert result.passed is True
    assert result.description == "raw_cv_texts: all rows usable"


def test_a_problem_counted_zero_times_is_not_a_problem():
    """Every check reports all its counts, most of them zero on a good run."""
    result = _result(
        {"blank name": 0, "duplicate id": 0},
        severity=AssetCheckSeverity.ERROR,
        subject="raw_candidates",
    )

    assert result.passed is True


def test_one_failing_count_fails_the_check():
    result = _result(
        {"blank name": 3},
        severity=AssetCheckSeverity.WARN,
        subject="raw_candidates",
    )

    assert result.passed is False
    assert result.description == "raw_candidates: blank name (3 rows)"


def test_several_problems_are_listed_together():
    result = _result(
        {"blank name": 3, "duplicate id": 2},
        severity=AssetCheckSeverity.ERROR,
        subject="raw_candidates",
    )

    assert result.description == (
        "raw_candidates: blank name (3 rows), duplicate id (2 rows)"
    )


def test_only_the_failing_problems_reach_the_metadata():
    result = _result(
        {"blank name": 3, "duplicate id": 0},
        severity=AssetCheckSeverity.ERROR,
        subject="raw_candidates",
    )

    assert result.metadata["problems_found"].data == {"blank name": 3}


def test_the_severity_it_is_given_is_the_severity_it_reports():
    result = _result({"x": 1}, severity=AssetCheckSeverity.WARN, subject="t")

    assert result.severity == AssetCheckSeverity.WARN


def test_table_names_are_backtick_quoted_for_bigquery():
    """Unquoted, a project id containing a hyphen is read as subtraction."""
    reference = _table("raw_cv_texts")

    assert reference.startswith("`")
    assert reference.endswith(".raw_cv_texts`")


# ── the four checks, against a client that answers with counts ────────────
class CountingClient:
    """Answers every COUNT query with the next number it was given."""

    def __init__(self, counts):
        self._counts = list(counts)
        self.queries: list[str] = []

    def query(self, query, job_config=None):
        self.queries.append(query)
        return self

    def result(self):
        value = self._counts.pop(0) if self._counts else 0
        return [[value]]


@pytest.fixture
def counts(monkeypatch):
    """Installs a client that returns the given sequence of counts."""

    def install(*values):
        client = CountingClient(values)
        monkeypatch.setattr(check_assets, "_client", lambda: client)
        return client

    return install


def test_a_clean_warehouse_passes_every_check(counts):
    counts()

    assert check_assets.raw_cv_texts_is_usable().passed is True
    counts()
    assert check_assets.entity_ids_are_unique_and_linked().passed is True
    counts()
    assert check_assets.entity_content_is_present().passed is True


def test_a_blank_submission_id_fails_the_raw_text_check(counts):
    counts(4)

    result = check_assets.raw_cv_texts_is_usable()

    assert result.passed is False
    assert "submission_id blank (4 rows)" in result.description


def test_a_duplicate_id_fails_the_entity_check(counts):
    counts(0, 2)

    result = check_assets.entity_ids_are_unique_and_linked()

    assert result.passed is False
    assert "duplicate submission_id" in result.description


def test_missing_content_warns_rather_than_blocking(counts):
    counts(1)

    result = check_assets.entity_content_is_present()

    assert result.passed is False
    assert result.severity == AssetCheckSeverity.WARN


def test_a_cv_that_produced_no_entities_is_reported(counts):
    counts(3, 300)

    result = check_assets.every_cv_produced_entities()

    assert result.passed is False
    assert result.description == (
        "3 of 300 CVs produced no work experience and no skills"
    )


def test_every_cv_producing_entities_passes(counts):
    counts(0, 300)

    result = check_assets.every_cv_produced_entities()

    assert result.passed is True
    assert result.description == "all 300 CVs produced entities"


def test_the_blank_count_query_treats_whitespace_as_blank(counts):
    client = counts(0)

    check_assets.raw_cv_texts_is_usable()

    assert "TRIM(submission_id) = ''" in client.queries[0]


def test_the_link_check_joins_against_the_cv_table(counts):
    client = counts()

    check_assets.entity_ids_are_unique_and_linked()

    assert any("raw_cv_texts" in query for query in client.queries)


def test_the_client_is_built_for_the_configured_project(monkeypatch):
    """The last line not otherwise reached: every check stubs this out."""
    monkeypatch.setattr(
        check_assets.bigquery, "Client", lambda project=None: ("client", project)
    )

    assert check_assets._client() == ("client", check_assets.PROJECT_ID)
