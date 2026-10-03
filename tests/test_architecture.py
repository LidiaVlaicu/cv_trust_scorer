"""
Enforces the pure-core boundary that the layer structure exists to express.

Every layer is split into `rules/` (pure decisions) and `assets/` (the I/O
shell that feeds them). That split is what lets 219 tests run in about a
second with no warehouse and no mocking, and it is what makes each rule
testable in isolation for the thesis.

A convention held up only by good intentions erodes: one `from google.cloud
import bigquery` inside a rules module, and the pure core quietly stops being
pure. These tests read the import statements and fail when that happens, so
the architecture is a property of the codebase rather than a claim about it.
"""

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Importing any of these means the module performs I/O, needs credentials, or
# is tied to the orchestrator - none of which belongs in a pure rule.
FORBIDDEN_IN_RULES = {
    "google.cloud",
    "google.api_core",
    "dagster",
    "anthropic",
    "fitz",
    "pymupdf",
    "requests",
    "dotenv",
    "os",  # reading the environment is configuration, i.e. I/O
}

LAYERS = ("bronze", "silver", "gold")


def rules_modules() -> list[Path]:
    """Every module under a `rules/` folder in any layer."""
    found: list[Path] = []
    for layer in LAYERS:
        found.extend(sorted((REPO_ROOT / layer / "rules").glob("*.py")))
    return [path for path in found if path.name != "__init__.py"]


def imported_names(path: Path) -> set[str]:
    """Top-level module names imported by `path`, however they are spelled."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_there_are_rules_modules_to_check():
    """Guards against the suite below passing because it found nothing."""
    modules = rules_modules()
    assert len(modules) >= 5, f"expected rules modules in every layer, got {modules}"


@pytest.mark.parametrize(
    "module", rules_modules(), ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_rules_modules_perform_no_io(module: Path):
    """
    A pure rule may not import the warehouse, the orchestrator, or an API.

    If this fails, the logic that needs I/O belongs in the sibling `assets/`
    module, which is free to import anything.
    """
    violations = sorted(
        imported for imported in imported_names(module)
        if any(
            imported == forbidden or imported.startswith(f"{forbidden}.")
            for forbidden in FORBIDDEN_IN_RULES
        )
    )
    assert not violations, (
        f"{module.relative_to(REPO_ROOT)} imports {violations}. "
        "Pure rules must stay I/O-free - move that part into the assets/ shell."
    )


@pytest.mark.parametrize(
    "module", rules_modules(), ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_rules_modules_never_import_an_assets_module(module: Path):
    """
    Dependencies point one way: assets import rules, never the reverse.

    A rule reaching into an asset would drag the warehouse in behind it and
    make the layer circular.
    """
    offending = sorted(
        imported for imported in imported_names(module)
        if ".assets" in imported or imported.endswith("assets")
    )
    assert not offending, (
        f"{module.relative_to(REPO_ROOT)} imports {offending}; "
        "rules must not depend on the I/O shell."
    )


def test_reference_data_is_pure_too():
    """
    The seniority ladder is reference data expressed in code, so it is imported
    by rules modules and must be as pure as they are.
    """
    ladder = REPO_ROOT / "reference" / "seniority_ladder.py"
    violations = sorted(
        imported for imported in imported_names(ladder)
        if any(
            imported == forbidden or imported.startswith(f"{forbidden}.")
            for forbidden in FORBIDDEN_IN_RULES
        )
    )
    assert not violations, f"reference/seniority_ladder.py imports {violations}"


def test_every_layer_has_both_halves():
    """The structure is uniform: each layer separates rules from assets."""
    for layer in LAYERS:
        assert (REPO_ROOT / layer / "rules").is_dir(), f"{layer}/rules missing"
        assert (REPO_ROOT / layer / "assets").is_dir(), f"{layer}/assets missing"
