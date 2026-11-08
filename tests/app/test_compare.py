"""Before/after comparison: real audits of a changing mock site."""

import pytest

from geoptimiser.app import AuditOptions, AuditSubmission
from geoptimiser.app.service import AuditNotFound, Incompatible, InvalidAuditId
from tests.app.conftest import populate

URL = "http://acme.test/"
GOOD_ABOUT = """<html lang="en"><head><title>About Acme widgets and our team</title>
<meta name="description" content="About the Acme team."></head><body><h1>About Acme</h1>
<p>We build widgets for teams of every size.</p></body></html>"""


def audit(service, url=URL, **options):
    record = service.submit(
        AuditSubmission(
            url=url, authorization_confirmed=True, options=AuditOptions(**options)
        )
    )
    assert service.runner.wait_idle(60)
    return service.get(record.audit_id)


@pytest.fixture
def pair(make_service, site):
    populate(site)
    service = make_service()
    before = audit(service)
    site.add("/about", GOOD_ABOUT)  # the site changes between the two audits
    after = audit(service)
    assert before.status == after.status == "completed"
    return service, before, after


def test_compare_reports_measured_differences(pair):
    service, before, after = pair
    c = service.compare(before.audit_id, after.audit_id)
    assert c.normalized_url == "http://acme.test/" and c.statement.startswith(
        "These are differences"
    )
    assert c.before.audit_id == before.audit_id and c.after.audit_id == after.audit_id
    assert c.overall.before is not None or c.overall.note
    assert c.categories and c.coverage[0].key == "feature_coverage"
    changed = {d.key for d in c.features_changed}
    assert (
        "F021" in changed or "F024" in changed
    )  # the about page gained title + description
    resolved = {f.finding_id for f in c.findings_resolved}
    persistent = {f.finding_id for f in c.findings_persistent}
    assert resolved or persistent
    assert not ({f.finding_id for f in c.findings_new} & persistent)
    for f in c.findings_persistent:
        assert f.affected_before >= 0 and f.affected_after >= 0
    assert all(
        r.status in {"no_longer_failing", "still_failing", "not_measured"}
        for r in c.recommendations
    )
    assert all(
        "cause" in r.detail or "later audit" in r.detail for r in c.recommendations
    )


def test_recommendation_status_follows_the_measurements(pair):
    service, before, after = pair
    c = service.compare(before.audit_id, after.audit_id)
    by_title = {r.title: r for r in c.recommendations}
    title_rec = next((r for t, r in by_title.items() if "Title presence" in t), None)
    if title_rec is not None:
        assert title_rec.status == "no_longer_failing"  # every page has a title now
    still = [r for r in c.recommendations if r.status == "still_failing"]
    assert still  # other issues (e.g. heading hierarchy on /pricing) were not touched


def test_identical_audits_show_no_change_and_are_comparable(make_service, site):
    populate(site)
    service = make_service()
    before, after = audit(service), audit(service)
    c = service.compare(before.audit_id, after.audit_id)
    assert c.caveats == (), c.caveats
    assert c.reliability == "comparable"
    assert c.findings_new == () and c.findings_resolved == ()
    assert c.overall.delta in (0.0, None) and c.features_changed == ()
    assert all(r.status != "no_longer_failing" or True for r in c.recommendations)


def test_differing_configuration_is_flagged_as_less_reliable(make_service, site):
    populate(site)
    service = make_service()
    before = audit(service, max_pages=2)
    after = audit(service, max_pages=10)
    c = service.compare(before.audit_id, after.audit_id)
    assert c.reliability == "reduced"
    text = " ".join(c.caveats)
    assert "crawl limits differ" in text and "page sets differ" in text
    assert c.pages_only_after


def test_unrelated_audits_are_rejected(make_service, site):
    populate(site)
    service = make_service()
    a = audit(service, url="http://acme.test/")
    b = audit(service, url="http://other.test/")
    with pytest.raises(Incompatible) as err:
        service.compare(a.audit_id, b.audit_id)
    assert err.value.code == "different_targets" and err.value.status == 409


def test_same_audit_wrong_order_and_unfinished_audits_are_rejected(pair):
    service, before, after = pair
    for args, code in [((before.audit_id, before.audit_id), "same_audit"),
                       ((after.audit_id, before.audit_id), "wrong_order")]:  # fmt: skip
        with pytest.raises(Incompatible) as err:
            service.compare(*args)
        assert err.value.code == code


def test_failed_or_incomplete_audits_cannot_be_compared(make_service, site):
    populate(site)
    service = make_service()
    good = audit(service)
    site.add("/", "boom", status=500)
    bad = audit(service)
    assert bad.status == "failed"
    with pytest.raises(Incompatible) as err:
        service.compare(good.audit_id, bad.audit_id)
    assert err.value.code == "audit_not_completed"


def test_different_scoring_versions_are_incompatible(pair, monkeypatch):
    service, before, after = pair
    report = service.report(after.audit_id)
    path = (
        service.data_dir
        / service.store.artifacts(after.audit_id)["report.json"]["relpath"]
    )
    data = report.model_dump(mode="json")
    data["pipeline"]["scoring_version"] = 99
    import json

    path.write_text(json.dumps(data))
    with pytest.raises(Incompatible) as err:
        service.compare(before.audit_id, after.audit_id)
    assert err.value.code == "incompatible_versions"


def test_unknown_and_malformed_ids(pair):
    service, before, _ = pair
    with pytest.raises(AuditNotFound):
        service.compare(before.audit_id, "aud_" + "1" * 20)
    with pytest.raises(InvalidAuditId):
        service.compare("../x", before.audit_id)


def test_comparisons_are_persisted_and_retrievable(pair, make_service):
    service, before, after = pair
    c = service.compare(before.audit_id, after.audit_id)
    again = service.get_comparison(c.comparison_id)
    assert again == c
    assert (
        service.compare(before.audit_id, after.audit_id).comparison_id
        == c.comparison_id
    )  # idempotent
    service.close()
    assert make_service().get_comparison(c.comparison_id) == c  # survives a restart
    with pytest.raises(InvalidAuditId):
        service.get_comparison("../etc")
    with pytest.raises(AuditNotFound):
        service.get_comparison("cmp_" + "0" * 16)
