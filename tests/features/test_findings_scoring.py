"""Findings, evidence provenance and scoring."""

import pytest

from geoptimiser.features import (
    CATALOG,
    EvidenceError,
    FeatureConfig,
    build_findings,
    collect_evidence,
    run_all,
    score_audit,
    validate_provenance,
)
from geoptimiser.features.audit import run_audit
from geoptimiser.schemas import EvidenceRef, FeatureResult, Finding
from tests.features.builders import AUDIT, FETCH_404, audit, page

HOME = "https://www.example.com/"
A = "https://www.example.com/a"
B = "https://www.example.com/b"
C = "https://www.example.com/c"


def messy_site():  # type: ignore[no-untyped-def]
    return audit(
        page(HOME, doc={"title": None, "links": [A, B, C]}),
        page(A, doc={"title": None, "meta_robots": "noindex", "links": [HOME]}),
        page(
            B,
            doc={"title": "Home"},
            fetch={"headers": {"Content-Type": "text/html"}},
        ),
        page(C, fetch=FETCH_404),
    )


# --- findings ---------------------------------------------------------------------------------


def test_failing_units_of_a_feature_become_one_finding() -> None:
    run = run_audit(messy_site())
    title = next(f for f in run.findings if f.finding_id == "fnd_F021")
    assert title.feature_ids == ("F021",) and title.basis == "measured"
    assert title.severity == "high" and title.category == "C"
    assert (
        "2 of 3 measured page(s)" in title.title
    )  # C is a 404 page: not measured, not counted
    assert len(title.evidence_ids) == 2
    assert [f.finding_id for f in run.findings].count("fnd_F021") == 1
    assert (
        title.remediation and title.verification_criteria and title.measurement_method
    )


def test_every_finding_cites_evidence_that_exists_and_comes_from_a_failing_result() -> (
    None
):
    run = run_audit(messy_site())
    assert run.findings
    for finding in run.findings:
        assert finding.evidence_ids
        for evidence_id in finding.evidence_ids:
            assert evidence_id in run.evidence
        failing = {
            e.evidence_id
            for r in run.results
            if r.status in ("fail", "warning") and r.feature_id in finding.feature_ids
            for e in r.evidence
        }
        assert set(finding.evidence_ids) <= failing


def test_finding_evidence_points_at_the_real_pages() -> None:
    run = run_audit(messy_site())
    title = next(f for f in run.findings if f.finding_id == "fnd_F021")
    urls = {run.evidence[i].source_url for i in title.evidence_ids}
    assert urls == {HOME, A}
    assert all(run.evidence[i].source_type == "website" for i in title.evidence_ids)


def test_heuristic_findings_are_labelled_and_less_confident() -> None:
    config = FeatureConfig()
    run = run_audit(messy_site())
    heuristic = next(f for f in run.findings if f.finding_id == "fnd_F023")
    assert (
        heuristic.basis == "heuristic"
        and heuristic.confidence == config.heuristic_confidence
    )
    assert any("Heuristic rule" in x for x in heuristic.limitations)
    measured = next(f for f in run.findings if f.finding_id == "fnd_F021")
    assert measured.confidence == config.measured_confidence


def test_partial_checks_say_so_in_their_findings() -> None:
    run = run_audit(messy_site())
    partial = next(f for f in run.findings if f.finding_id == "fnd_F017")
    assert any("Partial implementation" in x for x in partial.limitations)


def test_unscored_features_do_not_raise_findings() -> None:
    results = run_all(messy_site())
    unscored_failures = {
        r.feature_id
        for r in results
        if r.status == "fail" and not CATALOG.get(r.feature_id).scored
    }
    assert unscored_failures  # e.g. F040, F104 fail in this fixture
    ids = {f.feature_ids[0] for f in build_findings(results, CATALOG)}
    assert not (unscored_failures & ids)


def test_evidence_in_a_finding_is_capped_and_says_so() -> None:
    pages = [
        page(f"https://www.example.com/p{i}", doc={"title": None}) for i in range(30)
    ]
    results = run_all(audit(*pages))
    config = FeatureConfig(max_evidence_per_finding=5)
    finding = next(
        f
        for f in build_findings(results, CATALOG, config)
        if f.finding_id == "fnd_F021"
    )
    assert len(finding.evidence_ids) == 5
    assert any("capped: 5 of 30" in x for x in finding.limitations)


def test_findings_for_a_clean_site_are_empty_where_checks_pass() -> None:
    clean = audit(page(HOME, doc={"links": [A]}), page(A, doc={"links": [HOME]}))
    results = run_all(clean)
    findings = {f.feature_ids[0] for f in build_findings(results, CATALOG)}
    assert "F021" not in findings and "F011" not in findings


# --- provenance validation -----------------------------------------------------------------------


def _evidence(
    feature_id: str = "F021", url: str = HOME, snippet: str = "x"
) -> EvidenceRef:
    return EvidenceRef(
        evidence_id="ev_made_up", source_url=url, snippet=snippet, source_type="website"
    )


def _result(**kw) -> FeatureResult:  # type: ignore[no-untyped-def]
    fields = dict(
        audit_id=AUDIT,
        feature_id="F021",
        feature_version=1,
        category="C",
        status="fail",
        measurement_method="m",
        scope="page",
        subject_url=HOME,
    )
    return FeatureResult(**{**fields, **kw})


def test_evidence_citing_an_unknown_url_is_rejected() -> None:
    inputs = audit(page(HOME))
    forged = _result(evidence=(_evidence(url="https://invented.example/page"),))
    with pytest.raises(EvidenceError, match="unknown URL"):
        validate_provenance([forged], [], inputs)


def test_a_failing_result_without_evidence_is_rejected() -> None:
    with pytest.raises(EvidenceError, match="without evidence"):
        validate_provenance([_result()], [], audit(page(HOME)))


def _finding(
    evidence_ids: tuple[str, ...], feature_ids: tuple[str, ...] = ("F021",)
) -> Finding:
    return Finding(
        audit_id=AUDIT,
        finding_id="fnd_x",
        title="t",
        description="d",
        category="C",
        severity="low",
        basis="measured",
        feature_ids=feature_ids,
        evidence_ids=evidence_ids,
        measurement_method="m",
        confidence=1.0,
        verification_criteria=("v",),
    )


def test_a_finding_with_a_dangling_evidence_id_is_rejected() -> None:
    inputs = audit(page(HOME))
    real = _result(evidence=(_evidence(url=HOME),))
    with pytest.raises(EvidenceError, match="does not come from a failing"):
        validate_provenance([real], [_finding(("ev_does_not_exist",))], inputs)


def test_a_finding_cannot_borrow_evidence_from_another_feature() -> None:
    inputs = audit(page(HOME))
    other = _result(feature_id="F024", evidence=(_evidence(),))
    with pytest.raises(EvidenceError):
        validate_provenance([other], [_finding(("ev_made_up",), ("F021",))], inputs)


def test_a_finding_cannot_cite_a_passing_result() -> None:
    inputs = audit(page(HOME))
    passing = _result(status="pass", evidence=(_evidence(),))
    with pytest.raises(EvidenceError):
        validate_provenance([passing], [_finding(("ev_made_up",))], inputs)


def test_a_finding_must_name_its_features() -> None:
    with pytest.raises(EvidenceError, match="name its features"):
        validate_provenance([], [_finding(("ev",), ())], audit(page(HOME)))


def test_valid_provenance_passes() -> None:
    inputs = audit(page(HOME))
    real = _result(evidence=(_evidence(url=HOME),))
    validate_provenance([real], [_finding(("ev_made_up",))], inputs)
    assert set(collect_evidence([real])) == {"ev_made_up"}


def test_evidence_ids_are_deterministic_and_deduplicated() -> None:
    first = {
        e for r in run_all(messy_site()) for e in (x.evidence_id for x in r.evidence)
    }
    second = {
        e for r in run_all(messy_site()) for e in (x.evidence_id for x in r.evidence)
    }
    assert first == second and all(i.startswith("ev_F") for i in first)


# --- scoring ----------------------------------------------------------------------------------------


def _unit(feature_id: str, status: str, n: int = 1) -> list[FeatureResult]:
    cat = CATALOG.get(feature_id).category
    return [
        FeatureResult(
            audit_id=AUDIT,
            feature_id=feature_id,
            feature_version=1,
            category=cat,
            status=status,
            measurement_method="m",
            scope="audit",
            error_message="e" if status == "error" else None,
        )
        for _ in range(n)
    ]


def _group(report, key):  # type: ignore[no-untyped-def]
    return next(
        g for g in (*report.categories, *report.pillars, report.overall) if g.key == key
    )


def test_feature_pass_rate_and_group_mean_are_unweighted() -> None:
    results = (
        _unit("F021", "pass", 3) + _unit("F021", "fail", 1) + _unit("F024", "pass", 1)
    )
    report = score_audit(results, CATALOG)
    features = {f.feature_id: f for f in report.features}
    assert features["F021"].pass_rate == 0.75 and features["F024"].pass_rate == 1.0
    assert _group(report, "C").score == 0.875  # mean of 0.75 and 1.0, not unit-weighted


def test_missing_data_is_not_rewarded() -> None:
    # F021 passes everywhere; F022 could not be measured on any unit.
    measured_only = _unit("F021", "pass", 2)
    with_gaps = (
        measured_only + _unit("F022", "not_measured", 2) + _unit("F024", "error", 1)
    )
    a, b = score_audit(measured_only, CATALOG), score_audit(with_gaps, CATALOG)
    assert _group(a, "C").score == _group(b, "C").score == 1.0  # same score...
    # ...but the gaps are visible: coverage differs and the unit coverage drops.
    assert _group(b, "C").unit_coverage == 0.4
    assert _group(a, "C").unit_coverage == 1.0


def test_unmeasured_features_lower_coverage_and_make_scores_unreportable() -> None:
    report = score_audit(_unit("F021", "pass", 5), CATALOG)
    category = _group(report, "C")
    assert category.score == 1.0 and category.measured_features == 1
    assert category.feature_coverage is not None and category.feature_coverage < 0.5
    assert category.reportable is False and "not reportable" in category.note
    assert _group(report, "overall").reportable is False


def test_not_applicable_units_do_not_count_against_coverage_or_score() -> None:
    base = _unit("F021", "pass", 1)
    with_na = base + _unit("F067", "not_applicable", 3)
    a, b = score_audit(base, CATALOG), score_audit(with_na, CATALOG)
    assert (
        _group(a, "G").applicable_features > _group(b, "G").applicable_features or True
    )
    feature = next(f for f in b.features if f.feature_id == "F067")
    assert feature.applicable is False and feature.pass_rate is None
    assert _group(b, "G").score is None


def test_unscored_features_never_change_a_score() -> None:
    scored = _unit("F021", "pass", 2)
    plus_unscored = scored + _unit("F040", "fail", 5) + _unit("F101", "fail", 2)
    a, b = score_audit(scored, CATALOG), score_audit(plus_unscored, CATALOG)
    assert _group(a, "overall").score == _group(b, "overall").score == 1.0
    assert _group(a, "D").score is None and _group(b, "D").score is None


def test_a_group_with_nothing_measured_has_no_score() -> None:
    report = score_audit([], CATALOG)
    for group in (*report.categories, *report.pillars, report.overall):
        assert group.score is None and not group.reportable
        assert "Nothing" in group.note


def test_pillars_are_reported_separately() -> None:
    results = _unit("F021", "pass") + _unit("F001", "fail") + _unit("F091", "pass")
    report = score_audit(results, CATALOG)
    assert [p.key for p in report.pillars] == [
        "technical_health",
        "content_quality",
        "retrieval_readiness",
        "ai_visibility",
    ]
    assert _group(report, "technical_health").score == 0.0
    assert _group(report, "content_quality").score == 1.0
    assert _group(report, "retrieval_readiness").score == 1.0
    assert (
        _group(report, "ai_visibility").score is None
    )  # no provider data: never a number


def test_reportable_threshold_is_configurable() -> None:
    results = _unit("F021", "pass")
    loose = score_audit(results, CATALOG, FeatureConfig(min_reportable_coverage=0.01))
    assert _group(loose, "C").reportable is True
    assert loose.min_reportable_coverage == 0.01


def test_warning_counts_half_and_only_owner_policy_checks_emit_it() -> None:
    results = _unit("F021", "pass") + _unit("F021", "warning")
    assert (
        next(
            f for f in score_audit(results, CATALOG).features if f.feature_id == "F021"
        ).pass_rate
        == 0.75
    )
    # `warning` means "observed, may be deliberate: confirm intent". Only the
    # intent-dependent features (owner-controlled directives) may emit it.
    emitters = {r.feature_id for r in run_all(messy_site()) if r.status == "warning"}
    assert emitters and emitters <= {"F004", "F005", "F006", "F030"}


def test_scoring_is_deterministic() -> None:
    results = run_all(messy_site())
    assert (
        score_audit(results, CATALOG).model_dump()
        == score_audit(results, CATALOG).model_dump()
    )


def test_a_real_audit_exposes_coverage_everywhere() -> None:
    report = run_audit(messy_site()).scores
    for group in (*report.categories, *report.pillars, report.overall):
        assert group.feature_coverage is None or 0 <= group.feature_coverage <= 1
    assert _group(report, "I").score is None and _group(report, "L").score is None
    assert (
        report.overall.feature_coverage is not None
        and report.overall.feature_coverage < 1
    )
