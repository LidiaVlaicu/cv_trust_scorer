"""
Tests for the client factory and the dataset lookup every layer shares.

The lookup raises instead of returning None, so these cover the failure
paths: a missing variable surfaces here rather than as a query against
`project.None.some_table`.
"""

import pytest

from shared.bigquery_client import bigquery_client, dataset_name


class FakeClient:
    """Stands in for a bigquery.Client; only identity matters here."""


def test_an_injected_client_is_returned_unchanged():
    injected = FakeClient()

    assert bigquery_client(injected) is injected


def test_each_layer_resolves_to_its_own_variable(monkeypatch):
    monkeypatch.setenv("BQ_DATASET_BRONZE", "b")
    monkeypatch.setenv("BQ_DATASET_SILVER", "s")
    monkeypatch.setenv("BQ_DATASET_GOLD", "g")

    assert dataset_name("bronze") == "b"
    assert dataset_name("silver") == "s"
    assert dataset_name("gold") == "g"


def test_an_override_wins_over_the_environment(monkeypatch):
    monkeypatch.setenv("BQ_DATASET_BRONZE", "from_env")

    assert dataset_name("bronze", override="explicit") == "explicit"


def test_an_override_is_used_even_when_the_variable_is_missing(monkeypatch):
    monkeypatch.delenv("BQ_DATASET_BRONZE", raising=False)

    assert dataset_name("bronze", override="explicit") == "explicit"


def test_an_unknown_layer_is_rejected():
    with pytest.raises(ValueError, match="unknown layer"):
        dataset_name("platinum")


def test_a_missing_variable_raises_rather_than_returning_none(monkeypatch):
    monkeypatch.delenv("BQ_DATASET_GOLD", raising=False)

    with pytest.raises(RuntimeError, match="BQ_DATASET_GOLD"):
        dataset_name("gold")


def test_an_empty_variable_counts_as_missing(monkeypatch):
    monkeypatch.setenv("BQ_DATASET_SILVER", "")

    with pytest.raises(RuntimeError, match="BQ_DATASET_SILVER"):
        dataset_name("silver")


def test_without_an_injected_client_one_is_built_for_the_project(monkeypatch):
    import importlib

    # shared/__init__ re-exports the function under this name, so the module
    # has to be fetched rather than reached through the package.
    module = importlib.import_module("shared.bigquery_client")

    monkeypatch.setenv("GCP_PROJECT_ID", "a-project")
    monkeypatch.setattr(module.bigquery, "Client", lambda project=None: project)

    assert bigquery_client() == "a-project"
