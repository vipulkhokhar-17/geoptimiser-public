"""The full pipeline through the service, against a mock site (no real network)."""

import json
from pathlib import Path

import pytest

from geoptimiser.agent import ModelUnavailable
from geoptimiser.app import AuditOptions, AuditSubmission
from geoptimiser.app.service import AuditNotFound, InvalidAuditId, InvalidRequest
from tests.app.conftest import populate

URL = "http://acme.test/"


def submit(service, url=URL, **options):
    record = service.submit(
        AuditSubmission(
            url=url, authorization_confirmed=True, options=AuditOptions(**options)
        )
    )
    assert service.runner.wait_idle(60)
    return service.get(record.audit_id)


def test_full_audit_completes_and_persists_every_artifact(make_service, site):
    populate(site)
    service = make_service()
    record = submit(service)
    assert record.status == "completed", (record.error_category, record.error_message)
    assert record.error_category is None and record.finished_at is not None

    stages = {s.name: s.status for s in service.stages(record.audit_id)}
    assert stages == {
        "validate": "ok", "crawl": "ok", "extract": "ok", "features": "ok", "chunk": "ok",
        "retrieval": "ok", "diagnose": "ok", "recommend": "ok", "agent": "skipped",
        "validate_output": "ok", "report": "ok",
    }  # fmt: skip

    artifacts = service.store.artifacts(record.audit_id)
    for name in ("fetches.jsonl", "documents.jsonl", "chunks.jsonl", "findings.json",
                 "recommendations.json", "report.json", "report.html", "features/features.json"):  # fmt: skip
        assert name in artifacts and artifacts[name]["sha256"]
    assert (service.data_dir / artifacts["report.json"]["relpath"]).is_file()

    report = service.report(record.audit_id)
    assert report.status == "completed" and report.findings_available
    assert (
        report.scores is not None and report.scores["overall"]["reportable"] is not None
    )
    assert len(report.pages) == 3 and report.recommendations_validated
    assert record.summary["pages_ok"] == 3 and record.summary["findings"] == len(
        report.findings
    )


def test_findings_and_recommendations_keep_valid_evidence(make_service, site):
    populate(site)
    service = make_service()
    record = submit(service)
    findings = service.findings(record.audit_id)
    assert findings["count"] > 0
    recs = service.recommendations(record.audit_id)
    assert recs["count"] > 0
    evidence_ids = {
        e["evidence_id"] for f in findings["findings"] for e in f["evidence"]
    }
    for f in findings["findings"]:
        assert f["finding"]["evidence_ids"] and len(f["evidence"]) == len(
            f["finding"]["evidence_ids"]
        )
        for e in f["evidence"]:
            assert e["source_url"].startswith("http://acme.test")
    for rec in recs["recommendations"]:
        assert rec["finding_ids"] and rec["evidence_ids"] and rec["verification_plan"]
        assert set(rec["evidence_ids"]) <= evidence_ids
        assert rec["expected_impact_direction"] == "uncertain"


def test_network_measurements_report_what_the_transport_exposes(make_service, site):
    populate(site)
    service = make_service()
    record = submit(service)
    net = service.report(record.audit_id).network
    assert net is not None and net.fetches >= 4 and net.fetches_ok == 4
    assert net.timings["dns_ms"].measured == net.fetches
    assert net.timings["ttfb_ms"].measured == net.fetches
    # The mock transport does not expose connection steps: honestly "not measured".
    assert net.timings["connect_ms"].measured == 0
    assert net.timings["connect_ms"].not_measured == net.fetches
    assert net.timings["total_ms"].p50_ms is not None


def test_report_html_escapes_and_links_sources(make_service, site):
    populate(site)
    site.add(
        "/",
        "<html><head><title>x</title></head><body><h1>&lt;script&gt;alert(1)&lt;/script&gt;</h1></body></html>",
    )
    service = make_service()
    record = submit(service)
    html = service.report_html(record.audit_id)
    assert "<script" not in html and 'href="javascript' not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html  # shown as text, not run
    assert 'rel="noopener noreferrer nofollow"' in html
    assert "No change is guaranteed" in html


def test_an_unreachable_site_fails_with_a_category_and_a_partial_report(
    make_service, site
):
    populate(site)

    def dns_failure(host, port):
        raise __import__("socket").gaierror("nope")

    from geoptimiser.crawler import SafeFetcher

    def factory(config, store, audit_id, allowed):
        return SafeFetcher(
            config, store, audit_id, host_allowed=allowed, resolver=dns_failure
        )

    service = make_service(fetcher_factory=factory)
    record = submit(service)
    assert record.status == "failed" and record.error_category == "dns"
    assert "resolved" in record.error_message
    stages = {s.name: s for s in service.stages(record.audit_id)}
    assert stages["crawl"].status == "failed" and "extract" not in stages
    report = service.report(record.audit_id)  # a partial report is still produced
    assert (
        report.status == "failed"
        and report.scores is None
        and not report.findings_available
    )
    assert report.network is not None and report.network.errors_by_type["dns"] >= 1
    assert "failed" in service.report_html(record.audit_id)
    with pytest.raises(Exception) as err:
        service.findings(record.audit_id)
    assert err.value.code == "findings_unavailable"  # type: ignore[attr-defined]


def test_blocked_addresses_are_refused_by_the_crawler_not_bypassed(make_service, site):
    populate(site)
    from geoptimiser.crawler import SafeFetcher

    def factory(config, store, audit_id, allowed):  # the REAL policy, a private answer
        return SafeFetcher(
            config,
            store,
            audit_id,
            host_allowed=allowed,
            resolver=lambda h, p: ["10.0.0.7"],
        )

    record = submit(make_service(fetcher_factory=factory))
    assert record.status == "failed" and record.error_category == "blocked_target"
    assert site.requests == []  # nothing ever reached the server


def test_the_default_fetcher_keeps_the_ssrf_policy(make_service):
    import tempfile

    from geoptimiser.app.pipeline import default_fetcher_factory
    from geoptimiser.crawler import CrawlConfig, LocalBodyStore

    with tempfile.TemporaryDirectory() as tmp:
        fetcher = default_fetcher_factory(
            CrawlConfig(), LocalBodyStore(Path(tmp)), "aud_x", lambda h: True
        )
        assert fetcher.ip_policy.__name__ == "is_public_address"
        result = fetcher.fetch("http://127.0.0.1:80/")
        assert result.record.error_type == "blocked_address"


def test_http_error_site_is_a_failed_audit_not_a_completed_one(make_service, site):
    populate(site)
    site.add("/", "gone", status=500)
    record = submit(make_service(), max_depth=0)
    assert record.status == "failed" and record.error_category == "http_error"


def test_unextractable_site_fails_with_no_content(make_service, site):
    populate(site)
    site.add("/", b"%PDF", content_type="application/pdf")
    record = submit(make_service())
    assert record.status == "failed" and record.error_category == "no_content"


def test_crawl_limits_come_from_the_server_not_the_client(make_service, site):
    populate(site)
    service = make_service(max_pages_cap=2)
    with pytest.raises(InvalidRequest) as err:
        service.submit(
            AuditSubmission(
                url=URL, authorization_confirmed=True, options=AuditOptions(max_pages=5)
            )
        )
    assert err.value.code == "options_out_of_range"
    record = submit(service, max_pages=2)
    assert record.status == "completed" and record.summary["pages_ok"] == 2


# --- optional stages ------------------------------------------------------------------------


def test_semantic_retrieval_unavailable_makes_the_audit_incomplete_not_completed(
    make_service, site
):
    pytest.importorskip("pydantic")
    populate(site)
    record = submit(make_service(), retrieval="semantic")
    # No sentence-transformers / weights in the default environment: an explicit failure.
    if record.status == "completed":
        pytest.skip("a semantic model is installed here")
    assert (
        record.status == "incomplete"
        and record.error_category == "retrieval_unavailable"
    )


def test_agent_failure_never_looks_like_success_and_deterministic_results_survive(
    make_service, site
):
    populate(site)

    def no_key(config):
        raise ModelUnavailable("OPENROUTER_API_KEY is not set")

    service = make_service(model_factory=no_key)
    record = submit(service, use_agent=True)
    assert (
        record.status == "incomplete" and record.error_category == "agent_unavailable"
    )
    report = service.report(record.audit_id)
    assert report.agent["status"] == "unavailable" and report.agent["requested"] is True
    assert (
        report.findings_available and report.recommendations_validated
    )  # deterministic work kept
    assert {s["name"]: s["status"] for s in report.stages}["agent"] == "failed"
    assert "OPENROUTER_API_KEY" not in json.dumps(report.model_dump(mode="json"))


def test_agent_can_be_disabled_by_the_operator(make_service, site):
    populate(site)
    service = make_service(agent_enabled=False)
    with pytest.raises(InvalidRequest) as err:
        service.submit(
            AuditSubmission(
                url=URL,
                authorization_confirmed=True,
                options=AuditOptions(use_agent=True),
            )
        )
    assert err.value.code == "agent_disabled"


def test_a_successful_scripted_agent_run_is_recorded(make_service, site):
    pytest.importorskip("langgraph")
    populate(site)
    from tests.agent.conftest import HAPPY, ScriptedModel

    service = make_service(model_factory=lambda cfg: ScriptedModel(list(HAPPY)))
    record = submit(service, use_agent=True)
    assert record.status == "completed", (record.error_category, record.error_message)
    agent = service.report(record.audit_id).agent
    assert agent["status"] == "completed" and agent["steps"] == 6
    assert "agent_trace.json" in service.store.artifacts(record.audit_id)


def test_an_incomplete_agent_run_makes_the_audit_incomplete(make_service, site):
    pytest.importorskip("langgraph")
    populate(site)
    from tests.agent.conftest import ScriptedModel, call

    service = make_service(
        model_factory=lambda cfg: ScriptedModel(
            [call("list_findings"), '{"action":"finish"}']
        )
    )
    record = submit(service, use_agent=True)
    assert record.status == "incomplete" and record.error_category == "agent_incomplete"


# --- ids and errors ------------------------------------------------------------------------


def test_unknown_and_malformed_ids(make_service):
    service = make_service()
    with pytest.raises(AuditNotFound):
        service.get("aud_" + "0" * 20)
    for bad in (
        "../../etc/passwd",
        "aud_xyz",
        "",
        "aud_" + "0" * 21,
        "AUD_" + "0" * 20,
    ):
        with pytest.raises(InvalidAuditId):
            service.get(bad)


def test_authorization_and_targets_are_validated(make_service):
    service = make_service()
    with pytest.raises(InvalidRequest) as err:
        service.submit(AuditSubmission(url=URL, authorization_confirmed=False))
    assert err.value.code == "authorization_required"
    for url in ("http://localhost/", "http://127.0.0.1/", "ftp://acme.test/", "http://user:pw@acme.test/",
                "http://acme.test:8080/", "http://intranet/", "http://printer.local/", "file:///etc/passwd"):  # fmt: skip
        with pytest.raises(InvalidRequest) as err:
            service.submit(AuditSubmission(url=url, authorization_confirmed=True))
        assert err.value.code == "invalid_target", url


def test_unexpected_stage_errors_are_contained_and_not_leaked(
    make_service, site, monkeypatch
):
    populate(site)
    import geoptimiser.app.pipeline as pipeline

    def boom(*a, **k):
        raise RuntimeError("secret /home/user/path")

    monkeypatch.setattr(pipeline, "run_audit", boom)
    record = submit(make_service())
    assert record.status == "failed" and record.error_category == "internal_error"
    assert "secret" not in (record.error_message or "") and "/home" not in (
        record.error_message or ""
    )
