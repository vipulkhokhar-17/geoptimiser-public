import pytest

from geoptimiser.features import CATALOG, default_registry, run_category, run_feature
from geoptimiser.features.registry import CHECKS, Check, FeatureRegistry
from tests.features.builders import audit, page


def test_default_registry_matches_the_catalog() -> None:
    registry = default_registry()
    implemented = {f.feature_id for f in CATALOG.features if f.measurable_now}
    assert set(registry.implemented_ids()) == implemented
    assert len(implemented) == 82  # 81 before F110 was implemented


def test_counts_by_status_are_documented_numbers() -> None:
    from collections import Counter

    counts = Counter(f.implementation_status for f in CATALOG.features)
    # F110 implemented in the final-assignment session (was planned).
    assert counts == {"implemented": 41, "partial": 41, "planned": 36, "unavailable": 2}


def test_categories_with_working_checks() -> None:
    working = {f.category for f in CATALOG.features if f.measurable_now}
    assert working == set("ABCDEFGHIJK")  # only L (AI visibility) has none


def test_registry_rejects_an_implemented_feature_without_a_check() -> None:
    checks = {k: v for k, v in CHECKS.items() if k != "F021"}
    with pytest.raises(ValueError, match="F021 is implemented but has no check"):
        FeatureRegistry(CATALOG, checks)


def test_registry_rejects_a_check_for_a_planned_feature() -> None:
    checks = {**CHECKS, "F008": Check("F008", "site", "none", 1, lambda ctx: None)}
    with pytest.raises(ValueError, match="F008 is planned but has a check"):
        FeatureRegistry(CATALOG, checks)


def test_registry_rejects_scope_and_version_drift() -> None:
    drift = Check("F021", "site", "document", 1, CHECKS["F021"].fn)
    with pytest.raises(ValueError, match="scope"):
        FeatureRegistry(CATALOG, {**CHECKS, "F021": drift})
    old = Check("F021", "page", "document", 2, CHECKS["F021"].fn)
    with pytest.raises(ValueError, match="version"):
        FeatureRegistry(CATALOG, {**CHECKS, "F021": old})


def test_a_new_check_is_added_without_touching_the_engine() -> None:
    """Extension point: a registry accepts extra definitions/checks."""
    registry = default_registry()
    assert registry.catalog.get("F021").feature_id in registry.checks


def test_run_feature_executes_one_feature() -> None:
    results = run_feature("F021", audit(page("https://www.example.com/")))
    assert [r.feature_id for r in results] == ["F021"]
    assert results[0].status == "pass"


def test_run_category_runs_only_that_category() -> None:
    results = run_category("C", audit(page("https://www.example.com/")))
    assert {r.category for r in results} == {"C"}
    assert {r.feature_id for r in results} == {
        f.feature_id for f in CATALOG.by_category("C")
    }


def test_unknown_feature_is_a_key_error() -> None:
    with pytest.raises(KeyError):
        run_feature("F999", audit(page("https://www.example.com/")))
