"""A score that is withheld is withheld everywhere it could be displayed (A4, B6)."""

import re
from pathlib import Path

import pytest

from geoptimiser.app import AuditOptions, AuditSubmission
from geoptimiser.app.report import render_html, shown_score
from tests.app.conftest import populate

URL = "http://acme.test/"
UI = Path(__file__).parents[2] / "src" / "geoptimiser" / "app" / "ui" / "app.js"


def audit(service):
    record = service.submit(
        AuditSubmission(url=URL, authorization_confirmed=True, options=AuditOptions())
    )
    assert service.runner.wait_idle(60)
    return service.report(record.audit_id)


def test_shown_score_is_only_ever_a_reportable_one() -> None:
    reportable = {"score": 0.9, "reportable": True, "reported_score": 0.9}
    withheld = {"score": 0.9, "reportable": False, "reported_score": None}
    assert shown_score(reportable) == 0.9
    assert shown_score(withheld) is None  # the computed value must not leak


def test_version_one_reports_follow_the_same_rule() -> None:
    old_ok = {"score": 0.8, "reportable": True}
    old_low = {"score": 0.8, "reportable": False}
    assert shown_score(old_ok) == 0.8 and shown_score(old_low) is None


def test_html_report_withholds_low_coverage_category_scores(make_service, site) -> None:
    populate(site)
    report = audit(make_service())
    assert report.report_version == 2 and report.scores is not None
    withheld = [c for c in report.scores["categories"] if not c["reportable"]]
    assert withheld, "a small site cannot measure every category"
    html = render_html(report)
    for c in withheld:
        assert c["reported_score"] is None and c["withheld_reason"]
        row = re.search(rf"<tr><td>{re.escape(c['name'])}</td><td>([^<]*)</td>", html)
        assert row, c["name"]
        cell = row.group(1)
        assert "withheld" in cell or "not measured" in cell
        if c["score"] is not None:  # a computed value exists but must stay hidden
            assert f"{c['score']:.3f}" not in cell
    assert "Why withheld" in html and "not a result for it" in html
    overall = report.scores["overall"]
    assert overall["reported_score"] is None or overall["reportable"]


def test_report_json_carries_counts_and_reason_for_every_group(
    make_service, site
) -> None:
    populate(site)
    report = audit(make_service())
    assert report.scores is not None
    for group in (*report.scores["categories"], *report.scores["pillars"]):
        assert {"measured_features", "applicable_features", "feature_coverage"} <= set(
            group
        )
        if not group["reportable"]:
            assert group["withheld_reason"]
        else:
            assert group["reported_score"] == group["score"]
            assert group["withheld_reason"] is None


def test_report_lists_measurement_gaps_as_limits_not_findings(
    make_service, site
) -> None:
    populate(site)
    report = audit(make_service())
    assert report.measurement_gaps, "unimplemented-in-this-page checks must be listed"
    assert all(
        g["status"] in ("not_measured", "error") and g["reason"]
        for g in report.measurement_gaps
    )
    assert any("does not execute JavaScript" in x for x in report.limitations)


def test_findings_say_whether_they_count_toward_the_score(make_service, site) -> None:
    populate(site)
    report = audit(make_service())
    assert report.findings
    for rf in report.findings:
        assert rf.kind in ("defect", "notice")
        if rf.kind == "notice":
            assert rf.contributes_to_score is False


def test_ui_never_prints_a_raw_category_score() -> None:
    """The bundled UI must read reported_score (via shownScore), not group.score."""
    source = UI.read_text(encoding="utf-8")
    assert "function shownScore" in source and "reported_score" in source
    assert not re.search(r"fmt\(\s*(c|o|g|group)\.score\b", source)


@pytest.mark.parametrize("key", ["reported_score", "status", "withheld_reason"])
def test_group_score_model_exposes_the_explicit_reportability_fields(key: str) -> None:
    from geoptimiser.features.scoring import GroupScore

    assert key in GroupScore.model_fields
