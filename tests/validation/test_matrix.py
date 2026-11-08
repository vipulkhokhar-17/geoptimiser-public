"""The validation matrix accounts for the whole catalog, exactly once, and is current."""

import csv
import io

import pytest

from geoptimiser.features.catalog_data import CATALOG
from geoptimiser.features.config import FeatureConfig
from geoptimiser.validation import matrix
from geoptimiser.validation.judgments import THRESHOLDS

# The declared catalog state. A deliberate catalog change (adding, retiring or
# re-scoping features) updates these numbers in the same commit as the catalog, then
# runs `python -m geoptimiser.features --export` and
# `python -m geoptimiser.validation.matrix --write`. An accidental change fails here.
EXPECTED_CATALOG_VERSION = (
    3  # 3: F110 implemented, F001 v2 (429/503+Retry-After), F070 v2
)
EXPECTED_FEATURE_COUNT = 120
EXPECTED_CATEGORIES = "ABCDEFGHIJKL"


@pytest.fixture(scope="module")
def rows() -> list[dict[str, str]]:
    return matrix.build_rows()


def test_declared_catalog_state_matches_the_catalog() -> None:
    assert CATALOG.version == EXPECTED_CATALOG_VERSION
    assert len(CATALOG.features) == EXPECTED_FEATURE_COUNT, (
        "the catalog size changed: update EXPECTED_FEATURE_COUNT with the catalog "
        "and regenerate the exports and the matrix"
    )
    assert "".join(c.code for c in CATALOG.categories) == EXPECTED_CATEGORIES


def test_feature_ids_are_unique_stable_and_contiguous() -> None:
    ids = [f.feature_id for f in CATALOG.features]
    assert len(set(ids)) == len(ids)
    assert ids == [f"F{n:03d}" for n in range(1, len(ids) + 1)]  # never renumbered
    for f in CATALOG.features:  # category follows the ID block of ten
        assert f.category == EXPECTED_CATEGORIES[(int(f.feature_id[1:]) - 1) // 10]


def test_every_catalog_feature_appears_in_the_matrix_exactly_once(rows) -> None:  # type: ignore[no-untyped-def]
    assert [r["feature_id"] for r in rows] == [f.feature_id for f in CATALOG.features]
    assert matrix.completeness_problems(rows) == []


def test_no_matrix_cell_is_empty_and_dispositions_are_from_the_closed_set(rows) -> None:  # type: ignore[no-untyped-def]
    for r in rows:
        assert set(r) == set(matrix.COLUMNS)
        assert all(str(v).strip() for v in r.values()), r["feature_id"]
        assert r["disposition"] in matrix.DISPOSITIONS


def test_implementation_status_is_distinct_from_validation_status(rows) -> None:  # type: ignore[no-untyped-def]
    for r in rows:
        status = next(f for f in CATALOG.features if f.feature_id == r["feature_id"])
        runnable = status.implementation_status in ("implemented", "partial")
        if not runnable:
            assert r["validation_status"].startswith("V0")
            assert r["dimension_implementation_verified"] == "no"
        else:
            assert not r["validation_status"].startswith("V0")
        # No feature may claim an outcome that was never measured.
        assert r["dimension_ai_visibility_demonstrated"] == "no"
        assert r["dimension_business_outcome_demonstrated"] == "no"
        assert r["claim_empirically_validated"] == "no"
        assert r["dimension_diagnostic_accuracy_benchmarked"].startswith("no")


def test_unimplemented_features_claim_no_measurement(rows) -> None:  # type: ignore[no-untyped-def]
    for r in rows:
        if r["implementation_status"].split(" ")[0] in ("planned", "unavailable"):
            assert r["source_location"] == "(no check)"
            assert "not_measured" in r["missing_evidence_behavior"]


def test_ai_visibility_claims_are_never_called_supported(rows) -> None:  # type: ignore[no-untyped-def]
    for r in rows:
        if r["benefit_class"].startswith("AI-answer"):
            assert (
                "unsupported" in r["dimension_technical_rationale_supported"]
                or r["dimension_technical_rationale_supported"]
                in ("n/a", "plausible mechanism, unverified")
                or "partly" in r["dimension_technical_rationale_supported"]
            )
            assert r["dimension_ai_visibility_demonstrated"] == "no"


def test_every_threshold_setting_is_classified() -> None:
    assert set(THRESHOLDS) == set(FeatureConfig.model_fields)


def test_checked_in_matrix_and_audit_document_are_current(rows) -> None:  # type: ignore[no-untyped-def]
    csv_text = (
        matrix.ROOT / "docs/validation/feature_validation_matrix.csv"
    ).read_text(encoding="utf-8")
    assert csv_text == matrix.to_csv(rows), (
        "run: python -m geoptimiser.validation.matrix --write"
    )
    parsed = list(csv.DictReader(io.StringIO(csv_text)))
    assert len(parsed) == EXPECTED_FEATURE_COUNT
    audit = (matrix.ROOT / "docs/validation/GEOPTIMISER_FEATURE_AUDIT.md").read_text(
        encoding="utf-8"
    )
    assert matrix.generated_markdown(rows) in audit
    # Counts in the document agree with the catalog, not with a stale copy.
    counts = matrix.summary_counts(rows)
    assert counts["total"] == EXPECTED_FEATURE_COUNT
    assert sum(counts["by_disposition"].values()) == EXPECTED_FEATURE_COUNT
    assert sum(counts["by_implementation"].values()) == EXPECTED_FEATURE_COUNT


def test_three_classifications_are_complete_and_consistent() -> None:
    from geoptimiser.validation.levels import validation_levels
    from geoptimiser.validation.matrix import (
        DISPOSITION_CODES,
        IMPLEMENTATION_LEVELS,
        VALIDATION_LEVELS,
        build_rows,
    )

    rows = build_rows()
    shipped = validation_levels()
    assert sorted(shipped) == [f"F{n:03d}" for n in range(1, 121)]
    for r in rows:
        assert r["implementation_level"] in IMPLEMENTATION_LEVELS
        assert r["validation_level"] in VALIDATION_LEVELS
        assert r["disposition_code"] in DISPOSITION_CODES.values()
        # An unimplemented feature cannot carry any validation level above NOT_TESTED.
        if r["implementation_level"] in ("PLANNED", "UNAVAILABLE"):
            assert r["validation_level"] == "NOT_TESTED"
        # No feature may claim real-page or outcome validation without a real corpus.
        assert r["validation_level"] not in ("REAL_PAGE_VALIDATED", "OUTCOME_VALIDATED")
        assert shipped[r["feature_id"]]["validation_level"] == r["validation_level"]
