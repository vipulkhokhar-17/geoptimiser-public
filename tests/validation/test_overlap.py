"""Every overlap is found, judged and (where it matters) neutralised in the score."""

from geoptimiser.features.config import FeatureConfig
from geoptimiser.features.contribution import UNIT_OVERLAPS, redundant_units
from geoptimiser.features.registry import CHECKS
from geoptimiser.schemas import FeatureResult
from geoptimiser.validation.overlap import (
    EXACT,
    OVERLAP_DECISIONS,
    SHARED,
    candidate_pairs,
    catalog_overlaps,
    signatures,
)


def test_every_candidate_overlap_has_a_documented_decision() -> None:
    """Static-signature matches and catalog-declared neighbours must all be judged."""
    needed = {(a, b) for a, b, _ in candidate_pairs(1.0)} | catalog_overlaps()
    missing = sorted(needed - set(OVERLAP_DECISIONS))
    assert not missing, f"add a decision to OVERLAP_DECISIONS for {missing}"


def test_decisions_name_real_features_in_sorted_order_with_a_reason() -> None:
    for (a, b), (kind, why) in OVERLAP_DECISIONS.items():
        assert a < b, (a, b)
        assert len(why) > 30 and kind
    from geoptimiser.features.registry import default_registry

    known = {f.feature_id for f in default_registry().catalog.features}
    assert {x for pair in OVERLAP_DECISIONS for x in pair} <= known


def test_pairs_judged_to_double_count_are_neutralised_by_a_scoring_rule() -> None:
    """A decision of 'exact duplicate' or 'shared cause' on scored checks needs a rule."""
    rule_secondaries = {r.secondary for r in UNIT_OVERLAPS}
    handled_elsewhere = {  # secondary is unscored or excluded, so it cannot double count
        ("F017", "F079"),
        ("F009", "F072"),
    }
    from geoptimiser.features.registry import default_registry

    scored = {
        f.feature_id
        for f in default_registry().catalog.features
        if f.scored and f.measurable_now
    }
    for pair, (kind, _) in OVERLAP_DECISIONS.items():
        if kind not in (EXACT, SHARED) or pair in handled_elsewhere:
            continue
        a, b = pair
        if not (a in scored and b in scored):
            continue
        assert rule_secondaries & {a, b}, f"{pair} is judged as double counting"


def test_static_signatures_cover_every_registered_check() -> None:
    sigs = signatures()
    assert set(sigs) == set(CHECKS)
    assert sigs["F052"].data == {"doc.landmarks"}


def _result(fid: str, status: str, url: str, observed: object = None) -> FeatureResult:
    return FeatureResult(
        audit_id="a", feature_id=fid, feature_version=1, category="F" if fid < "F060" else "G",
        status=status, observed_value=observed, measurement_method="m",  # type: ignore[arg-type]
        scope="page", subject_url=url, explanation="x",
    )  # fmt: skip


def test_article_metadata_is_counted_once_when_the_property_features_already_fail() -> (
    None
):
    u = "https://e.com/post"
    both = [
        _result("F046", "fail", u),
        _result("F048", "fail", u),
        _result("F069", "fail", u, ["Article lacks author, datePublished"]),
    ]
    found = redundant_units(both, FeatureConfig())
    assert found[("F069", u)].home == "F046"


def test_a_missing_headline_or_a_passing_owner_keeps_f069_independent() -> None:
    u = "https://e.com/post"
    headline = [
        _result("F046", "fail", u),
        _result("F069", "fail", u, ["Article lacks headline, author"]),
    ]
    assert redundant_units(headline, FeatureConfig()) == {}
    owner_passes = [
        _result("F049", "pass", u),  # a Last-Modified header satisfied F049
        _result("F069", "fail", u, ["Article lacks dateModified"]),
    ]
    assert redundant_units(owner_passes, FeatureConfig()) == {}
