"""Scoring scenarios with expected values fixed in advance (docs/validation, section 9).

Every number below was worked out by hand from the scoring rules, not read off the
implementation. Category C has these scored, runnable features: F021, F022, F023,
F024, F025, F026, F027, F029 (F028 and F030 are unscored); it has no planned scored
feature, so its coverage is measured / applicable.
"""

import pytest

from geoptimiser.features import CATALOG, FeatureConfig, score_audit
from geoptimiser.features.contribution import feature_exclusions, redundant_units
from geoptimiser.features.findings import build_findings
from geoptimiser.features.inputs import CrawlFacts
from geoptimiser.schemas import FeatureResult

C_SCORED = ("F021", "F022", "F023", "F024", "F025", "F026", "F027", "F029")


def unit(
    feature_id: str,
    status: str,
    url: str | None = "https://e.com/",
    observed: object = None,
) -> FeatureResult:
    return FeatureResult(
        audit_id="aud_s",
        feature_id=feature_id,
        feature_version=1,
        category=CATALOG.get(feature_id).category,
        status=status,  # type: ignore[arg-type]
        observed_value=observed,
        measurement_method="m",
        scope="page",
        subject_url=url,
        explanation="x" if status != "error" else None,
        error_message="e" if status == "error" else None,
        severity="medium" if status in ("fail", "warning") else "informational",
        evidence=(),
    )


def category(report, code):  # type: ignore[no-untyped-def]
    return next(c for c in report.categories if c.key == code)


def test_the_scored_set_assumed_by_these_scenarios_is_the_catalog_s() -> None:
    scored = tuple(f.feature_id for f in CATALOG.by_category("C") if f.scored)
    assert scored == C_SCORED  # if this changes, redo the hand calculations below


def test_all_applicable_pass_gives_one_and_is_reportable_at_full_coverage() -> None:
    results = [unit(f, "pass") for f in C_SCORED]
    c = category(score_audit(results, CATALOG), "C")
    assert (c.score, c.feature_coverage, c.reportable) == (1.0, 1.0, True)
    assert c.reported_score == 1.0 and c.status == "reportable"
    assert c.withheld_reason is None


def test_independent_failures_each_lower_the_score() -> None:
    results = [unit(f, "pass") for f in C_SCORED[:6]] + [
        unit("F027", "fail"),
        unit("F029", "fail"),
    ]
    # 6 features pass (1.0), 2 fail (0.0): mean = 6/8.
    assert category(score_audit(results, CATALOG), "C").score == 0.75


def test_not_applicable_units_leave_numerator_and_denominator() -> None:
    results = [unit(f, "pass") for f in C_SCORED[:5]] + [
        unit("F026", "not_applicable"),
        unit("F027", "not_applicable"),
        unit("F029", "not_applicable"),
    ]
    c = category(score_audit(results, CATALOG), "C")
    # F026/F027/F029 applied nowhere, so 5 applicable features, all measured and passing.
    assert (c.applicable_features, c.measured_features, c.score) == (5, 5, 1.0)


def test_missing_data_never_raises_the_score() -> None:
    full = [unit(f, "pass") for f in C_SCORED[:4]] + [unit("F021", "fail")]
    with_gap = full + [unit("F029", "not_measured", url="https://e.com/x")]
    a = category(score_audit(full, CATALOG), "C")
    b = category(score_audit(with_gap, CATALOG), "C")
    assert a.score == b.score  # an unknown is not counted as a pass...
    assert b.unit_coverage < a.unit_coverage  # ...but it is visible as lost coverage


@pytest.mark.parametrize(
    ("measured", "reportable"),
    [(3, False), (4, True), (5, True), (8, True)],  # 4/8 = 0.5 is inclusive
)
def test_reportability_boundary_is_inclusive_at_the_minimum(
    measured: int, reportable: bool
) -> None:
    results = [unit(f, "pass") for f in C_SCORED[:measured]]
    c = category(score_audit(results, CATALOG), "C")
    assert c.reportable is reportable
    assert (c.reported_score is not None) is reportable
    assert c.score == 1.0  # the computed subset value exists either way
    if not reportable:
        assert c.status == "withheld_low_coverage"
        assert "withheld" in (c.withheld_reason or "")
        assert f"only {measured} of 8" in (c.withheld_reason or "")


def test_a_group_with_nothing_measured_has_no_score_and_says_why() -> None:
    c = category(score_audit([], CATALOG), "C")
    assert c.score is None and c.reported_score is None and not c.reportable
    assert c.status == "not_measured" and "none of the 8" in (c.withheld_reason or "")


def test_a_group_where_nothing_applies_is_distinguished_from_not_measured() -> None:
    results = [unit(f, "not_applicable") for f in C_SCORED]
    c = category(score_audit(results, CATALOG), "C")
    assert c.status == "no_applicable_features" and c.score is None


def test_empty_crawl_reports_no_scores_at_all() -> None:
    report = score_audit([], CATALOG)
    groups = [report.overall, *report.pillars, *report.categories]
    assert all(g.score is None and not g.reportable for g in groups)
    assert all(g.reported_score is None for g in groups)


def test_the_reporting_threshold_is_configurable_and_reported() -> None:
    results = [unit(f, "pass") for f in C_SCORED[:3]]
    loose = score_audit(results, CATALOG, FeatureConfig(min_reportable_coverage=0.3))
    assert category(loose, "C").reportable  # 3/8 = 0.375 >= 0.3


# --- double counting (A3) -------------------------------------------------------------


def test_one_missing_main_counts_once_not_twice() -> None:
    f52, f59 = unit("F052", "fail"), unit("F059", "fail", observed=["no main landmark"])
    report = score_audit([f52, f59], CATALOG)
    features = {f.feature_id: f for f in report.features}
    assert features["F052"].failed == 1
    assert features["F059"].failed == 0 and features["F059"].redundant_units == 1
    assert features["F059"].pass_rate is None  # nothing independent left to average


def test_a_landmark_problem_beyond_the_missing_main_still_counts() -> None:
    f52 = unit("F052", "fail")
    f59 = unit("F059", "fail", observed=["no main landmark", "2 navigation landmarks"])
    report = score_audit([f52, f59], CATALOG)
    assert {f.feature_id: f.failed for f in report.features}["F059"] == 1


def test_f059_failing_when_f052_passes_is_independent() -> None:
    # An <article> satisfies F052; F059 still wants a <main> landmark.
    results = [
        unit("F052", "pass"),
        unit("F059", "fail", observed=["no main landmark"]),
    ]
    report = score_audit(results, CATALOG)
    assert {f.feature_id: f.failed for f in report.features}["F059"] == 1


def test_overlap_suppression_is_per_url() -> None:
    a, b = "https://e.com/a", "https://e.com/b"
    results = [
        unit("F052", "fail", a),
        unit("F059", "fail", a, ["no main landmark"]),
        unit("F052", "pass", b),
        unit("F059", "fail", b, ["no main landmark"]),
    ]
    dropped = redundant_units(results, FeatureConfig())
    assert set(dropped) == {("F059", a)}


def test_the_folded_failure_stays_visible_in_the_primary_finding() -> None:
    from geoptimiser.schemas import EvidenceRef

    def with_evidence(r: FeatureResult) -> FeatureResult:
        ref = EvidenceRef(
            evidence_id=f"ev_{r.feature_id}_1",
            source_url=r.subject_url or "https://e.com/",
            snippet="s",
            source_type="website",
        )
        return r.model_copy(update={"evidence": (ref,)})

    results = [
        with_evidence(unit("F052", "fail")),
        with_evidence(unit("F059", "fail", observed=["no main landmark"])),
    ]
    findings = {f.finding_id: f for f in build_findings(results, CATALOG)}
    assert "fnd_F059" not in findings
    folded = findings["fnd_F052"]
    assert folded.feature_ids == ("F052", "F059")
    assert {"ev_F052_1", "ev_F059_1"} <= set(folded.evidence_ids)
    assert any("counted once" in x for x in folded.limitations)


# --- features that cannot discriminate (A3, C4) ---------------------------------------


def test_link_discovered_crawl_excludes_orphan_checks_that_cannot_fail() -> None:
    ex = feature_exclusions(FeatureConfig(), CrawlFacts(max_depth=2))
    assert set(ex) == {"F009", "F072", "F010"}
    assert all(reason for reason in ex.values())


def test_a_deeper_crawl_or_stricter_thresholds_make_them_real_checks_again() -> None:
    deep = feature_exclusions(FeatureConfig(), CrawlFacts(max_depth=5))
    assert "F010" not in deep  # depth 4-5 pages can now exceed the limit of 3
    strict = feature_exclusions(
        FeatureConfig(min_incoming_links=2), CrawlFacts(max_depth=5)
    )
    assert "F072" not in strict  # "weakly linked" is a different question to "orphan"


def test_without_crawl_facts_nothing_is_excluded() -> None:
    assert feature_exclusions(FeatureConfig(), None) == {}


def test_excluded_features_do_not_enter_numerator_or_denominator() -> None:
    results = [unit("F009", "pass"), unit("F010", "pass"), unit("F072", "pass")]
    results += [unit("F001", "fail")]
    report = score_audit(results, CATALOG, crawl=CrawlFacts(max_depth=2))
    a = category(report, "A")
    assert a.score == 0.0  # only F001 contributes; the three free passes do not
    assert set(report.excluded_features) == {"F009", "F010", "F072"}
    visible = {f.feature_id: f for f in report.features}
    assert visible["F009"].pass_rate == 1.0 and not visible["F009"].contributes
    assert visible["F009"].exclusion_reason


def test_unscored_owner_policy_checks_do_not_move_the_score_but_raise_notices() -> None:
    from geoptimiser.schemas import EvidenceRef

    ref = EvidenceRef(
        evidence_id="ev_F005_1",
        source_url="https://e.com/",
        snippet="s",
        source_type="website",
    )
    warn = unit("F005", "warning").model_copy(update={"evidence": (ref,)})
    report = score_audit([warn, unit("F001", "pass")], CATALOG)
    assert {f.feature_id: f for f in report.features}["F005"].scored is False
    assert category(report, "A").score == 1.0
    (notice,) = build_findings([warn], CATALOG)
    assert notice.finding_id == "fnd_F005" and "intent" in notice.title
    assert notice.confidence == FeatureConfig().heuristic_confidence
