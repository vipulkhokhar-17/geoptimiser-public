import json

import pytest
from pydantic import ValidationError

from geoptimiser.recommendations import (
    ImpactRule,
    RecommendationConfig,
    TemplateGenerator,
    validate_recommendations,
    write_outputs,
)
from geoptimiser.schemas import Finding
from tests.diagnosis.conftest import SITE, clock


def generate(diagnosis, **config):
    return TemplateGenerator(RecommendationConfig(**config)).generate(diagnosis, clock)


def with_findings(diagnosis, findings):
    return diagnosis.model_copy(update={"findings": tuple(findings)})


def edit(finding, **changes):
    return Finding.model_validate(finding.model_dump() | changes)


def by_finding(result):
    return {i: r for r in result.recommendations for i in r.finding_ids}


def test_recommendations_link_to_real_findings_and_evidence(diagnosis):
    result = generate(diagnosis)
    assert result.recommendations and not result.rejected
    assert validate_recommendations(result, diagnosis) == []
    findings = {f.finding_id: f for f in diagnosis.findings}
    for rec in result.recommendations:
        cited = {e for i in rec.finding_ids for e in findings[i].evidence_ids}
        assert rec.evidence_ids and set(rec.evidence_ids) <= cited
        assert rec.verification_plan and rec.proposed_change
        assert rec.audit_id == diagnosis.audit_id


def test_only_findings_with_remediation_are_used(diagnosis):
    result = generate(diagnosis)
    findings = {f.finding_id: f for f in diagnosis.findings}
    used = {i for r in result.recommendations for i in r.finding_ids}
    assert used == {i for i, f in findings.items() if f.remediation}
    assert set(result.skipped_finding_ids) == {
        i for i, f in findings.items() if not f.remediation
    }
    assert result.skipped_finding_ids and any(
        "no remediation" in n for n in result.notes
    )


def test_impact_is_uncertain_without_supporting_rules(diagnosis):
    result = generate(diagnosis)
    assert {r.expected_impact_direction for r in result.recommendations} == {
        "uncertain"
    }
    assert all("uncertain" in r.rationale for r in result.recommendations)


def test_justified_impact_rule_is_used_and_explained(diagnosis):
    rule = ImpactRule(
        feature_id="F029",
        direction="positive",
        justification="Observed in experiment E1.",
    )
    result = generate(diagnosis, impact_rules=(rule,))
    rec = by_finding(result)["fnd_F029"]
    assert rec.expected_impact_direction == "positive"
    assert "Observed in experiment E1." in rec.rationale
    other = by_finding(result)["fnd_F024"]
    assert other.expected_impact_direction == "uncertain"
    with pytest.raises(ValidationError):
        ImpactRule(feature_id="F029", direction="positive", justification="short")


def test_priority_follows_severity_table_and_heuristic_demotion(diagnosis):
    findings = {f.finding_id: f for f in diagnosis.findings}
    result = generate(diagnosis)
    rec = by_finding(result)["fnd_F021"]  # severity high, measured
    assert findings["fnd_F021"].severity == "high" and rec.priority == "P1"
    syn = by_finding(result)["syn_no_page_summary"]  # high, heuristic -> demoted
    assert syn.priority == "P2"
    flat = generate(diagnosis, demote_heuristic_only=False)
    assert by_finding(flat)["syn_no_page_summary"].priority == "P1"
    custom = generate(
        diagnosis,
        priority_by_severity={
            "critical": "P0",
            "high": "P0",
            "medium": "P1",
            "low": "P2",
            "informational": "P3",
        },
    )
    assert by_finding(custom)["fnd_F021"].priority == "P0"


def test_priority_table_must_be_complete():
    with pytest.raises(ValidationError):
        RecommendationConfig(priority_by_severity={"high": "P1"})


def test_effort_rules(diagnosis):
    assert by_finding(generate(diagnosis))["fnd_F021"].estimated_effort == "medium"
    small = generate(diagnosis, effort_by_feature={"F021": "small"})
    assert by_finding(small)["fnd_F021"].estimated_effort == "small"
    by_cat = generate(diagnosis, effort_by_category={"C": "large"})
    assert by_finding(by_cat)["fnd_F021"].estimated_effort == "large"
    scaled = generate(
        diagnosis, effort_by_feature={"F021": "small"}, large_scope_pages=1
    )
    # one affected page is not above a threshold of one, so no bump
    assert by_finding(scaled)["fnd_F021"].estimated_effort == "small"


def test_duplicate_remediations_are_merged(diagnosis):
    originals = {f.finding_id: f for f in diagnosis.findings}
    a = originals["fnd_F021"]
    b = edit(
        originals["fnd_F024"],
        remediation="  " + (a.remediation or "").upper() + " ",
    )
    result = generate(with_findings(diagnosis, [a, b]))
    assert len(result.recommendations) == 1
    rec = result.recommendations[0]
    assert set(rec.finding_ids) == {"fnd_F021", "fnd_F024"}
    assert set(rec.evidence_ids) == set(a.evidence_ids) | set(b.evidence_ids)
    assert "(+1 related)" in rec.title
    assert rec.confidence == min(a.confidence, b.confidence)
    assert validate_recommendations(result, with_findings(diagnosis, [a, b])) == []


def test_output_is_deterministic(diagnosis):
    assert generate(diagnosis) == generate(diagnosis)
    first = generate(diagnosis).model_dump_json()
    assert first == generate(diagnosis).model_dump_json()
    ids = [r.recommendation_id for r in generate(diagnosis).recommendations]
    assert len(set(ids)) == len(ids)


def test_unsupported_claims_in_guidance_are_rejected_not_rewritten(diagnosis):
    f = next(f for f in diagnosis.findings if f.finding_id == "fnd_F021")
    promising = edit(f, remediation="Add a title; this will increase citations by 40%.")
    d = with_findings(diagnosis, [promising])
    result = generate(d)
    assert result.recommendations == ()
    (rejected,) = result.rejected
    assert (
        rejected.finding_ids == ("fnd_F021",) and "unsupported claim" in rejected.reason
    )


def test_claims_in_verification_criteria_are_rejected(diagnosis):
    f = next(f for f in diagnosis.findings if f.finding_id == "fnd_F021")
    bad = edit(f, verification_criteria=("Expect a guaranteed visibility gain.",))
    result = generate(with_findings(diagnosis, [bad]))
    assert result.rejected and not result.recommendations


def test_urls_outside_the_evidence_are_rejected(diagnosis):
    f = next(f for f in diagnosis.findings if f.finding_id == "fnd_F021")
    stray = edit(f, remediation="Copy the title from https://elsewhere.example/page.")
    result = generate(with_findings(diagnosis, [stray]))
    assert (
        result.rejected and "not in the findings' evidence" in result.rejected[0].reason
    )
    ok = edit(f, remediation=f"Add a title like the one on {SITE}/good.")
    d = with_findings(diagnosis, [ok])
    assert generate(d).rejected  # /good is not evidence for F021 (only /bad is)


def test_a_rejected_group_does_not_block_the_others(diagnosis):
    fs = {f.finding_id: f for f in diagnosis.findings}
    bad = edit(fs["fnd_F021"], remediation="Guaranteed fix.")
    result = generate(with_findings(diagnosis, [bad, fs["fnd_F024"]]))
    assert [r.finding_ids for r in result.recommendations] == [("fnd_F024",)]
    assert len(result.rejected) == 1


def test_empty_diagnosis(diagnosis):
    result = generate(with_findings(diagnosis, []))
    assert result.recommendations == () and result.rejected == ()


def test_heuristic_basis_is_disclosed(diagnosis):
    syn = by_finding(generate(diagnosis))["syn_no_page_summary"]
    assert "heuristic" in syn.rationale and "review before acting" in syn.rationale


def test_validate_detects_broken_links(diagnosis):
    result = generate(diagnosis)
    rec = result.recommendations[0]

    def swap(**changes):
        from geoptimiser.schemas import Recommendation

        new = Recommendation.model_validate(rec.model_dump() | changes)
        return result.model_copy(
            update={"recommendations": (new, *result.recommendations[1:])}
        )

    assert any(
        "does not exist" in p
        for p in validate_recommendations(swap(finding_ids=("nope",)), diagnosis)
    )
    assert any(
        "evidence" in p
        for p in validate_recommendations(swap(evidence_ids=("ev_x",)), diagnosis)
    )
    other = next(
        e
        for e in diagnosis.evidence
        if e not in rec.evidence_ids
        and not any(
            e in f.evidence_ids
            for f in diagnosis.findings
            if f.finding_id in rec.finding_ids
        )
    )
    assert any(
        "not cited" in p
        for p in validate_recommendations(swap(evidence_ids=(other,)), diagnosis)
    )
    assert any(
        "unsupported claim" in p
        for p in validate_recommendations(
            swap(proposed_change="Triple your traffic."), diagnosis
        )
    )
    assert any(
        "different audit" in p
        for p in validate_recommendations(swap(audit_id="zzz"), diagnosis)
    )


def test_artifacts(diagnosis, tmp_path):
    result = generate(diagnosis)
    write_outputs(tmp_path / "out", diagnosis, result)
    data = json.loads((tmp_path / "out" / "recommendations.json").read_text())
    assert data["schema_version"] == 1 and len(data["recommendations"]) == len(
        result.recommendations
    )
    assert (tmp_path / "out" / "findings.json").exists()
    with pytest.raises(FileExistsError):
        write_outputs(tmp_path / "out", diagnosis, result)
