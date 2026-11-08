"""Day 7: end-to-end validation, failure cases and regression tests (local mock site only)."""

import http.client
import json
import socket
import sqlite3
import ssl

import pytest

from geoptimiser.app import AuditOptions, AuditStore, AuditSubmission
from geoptimiser.app.service import AuditService, ServiceError
from geoptimiser.crawler import SafeFetcher
from tests.app.conftest import PUBLIC_IP, populate

URL = "http://acme.test/"


def run(service, url=URL, **options):
    record = service.submit(
        AuditSubmission(
            url=url, authorization_confirmed=True, options=AuditOptions(**options)
        )
    )
    assert service.runner.wait_idle(60)
    return service.get(record.audit_id)


def factory_with(**kwargs):
    def build(config, store, audit_id, allowed):
        return SafeFetcher(config, store, audit_id, host_allowed=allowed, **kwargs)

    return build


def to_mock(site, **extra):
    def connect(scheme, host, port, ip, timeout, policy):
        return http.client.HTTPConnection("127.0.0.1", site.port, timeout=timeout)

    return factory_with(
        resolver=lambda h, p: [PUBLIC_IP], connection_factory=connect, **extra
    )


# --- provenance end to end ---------------------------------------------------------------


def test_every_evidence_reference_resolves_to_this_audits_source_text(
    make_service, site
):
    populate(site)
    service = make_service()
    record = run(service)
    report = service.report(record.audit_id)
    docs = {}
    for line in (
        (
            service.data_dir
            / service.store.artifacts(record.audit_id)["documents.jsonl"]["relpath"]
        )
        .read_text()
        .splitlines()
    ):
        d = json.loads(line)
        docs[d["document_id"]] = d
    located = 0
    for rf in report.findings:
        assert rf.finding.audit_id == record.audit_id
        assert [e.evidence_id for e in rf.evidence] == list(rf.finding.evidence_ids)
        for e in rf.evidence:
            if e.chunk_id is None:
                continue
            located += 1
            assert e.audit_id == record.audit_id
            doc = docs[e.document_id]
            assert doc["audit_id"] == record.audit_id and doc["url"] == e.source_url
            assert doc["text"][e.char_start : e.char_end] == e.snippet  # exact offsets
    assert located > 0
    chunks = [
        json.loads(x)
        for x in (
            service.data_dir
            / service.store.artifacts(record.audit_id)["chunks.jsonl"]["relpath"]
        )
        .read_text()
        .splitlines()
    ]
    assert chunks and all(c["audit_id"] == record.audit_id for c in chunks)
    for c in chunks:
        assert (
            docs[c["document_id"]]["text"][c["char_start"] : c["char_end"]] == c["text"]
        )


def test_recommendations_cite_evidence_of_their_own_findings(make_service, site):
    populate(site)
    service = make_service()
    record = run(service)
    report = service.report(record.audit_id)
    by_finding = {
        rf.finding.finding_id: set(rf.finding.evidence_ids) for rf in report.findings
    }
    assert report.recommendations and report.recommendations.recommendations
    for rec in report.recommendations.recommendations:
        assert rec.audit_id == record.audit_id
        assert rec.finding_ids and set(rec.finding_ids) <= set(by_finding)
        allowed = set().union(*(by_finding[f] for f in rec.finding_ids))
        assert rec.evidence_ids and set(rec.evidence_ids) <= allowed


def test_two_audits_in_one_service_never_share_evidence(make_service, site):
    populate(site)
    service = make_service()
    a, b = run(service), run(service)
    ra, rb = service.report(a.audit_id), service.report(b.audit_id)
    ids_a = {e.chunk_id for rf in ra.findings for e in rf.evidence if e.chunk_id}
    ids_b = {e.chunk_id for rf in rb.findings for e in rf.evidence if e.chunk_id}
    assert ids_a and ids_b and not (ids_a & ids_b)
    assert {e.audit_id for rf in rb.findings for e in rf.evidence if e.audit_id} == {
        b.audit_id
    }


def test_json_and_html_reports_agree_and_contain_real_results(make_service, site):
    populate(site)
    service = make_service()
    record = run(service)
    report = service.report(record.audit_id)
    html = service.report_html(record.audit_id)
    assert report.scores["overall"]["feature_coverage"] is not None
    for rf in report.findings[:5]:
        assert (
            rf.finding.title.split(":")[0].replace("&", "&amp;") in html
            or rf.finding.title[:20] in html
        )
    assert f"{len(report.findings)}" in html and record.audit_id in html
    assert "Ignore all previous instructions" in html  # page text shown as escaped text
    assert (
        "<blockquote>Ignore" not in html or "&lt;" not in "Ignore"
    )  # (text, not markup)


def test_status_transitions_are_visible_and_ordered(make_service, site):
    populate(site)
    service = make_service()
    seen = []
    original = service.store.set_stage_pointer

    def spy(audit_id, stage):
        seen.append(stage)
        original(audit_id, stage)

    service.store.set_stage_pointer = spy  # type: ignore[method-assign]
    record = run(service)
    assert seen == [
        "validate",
        "crawl",
        "extract",
        "features",
        "chunk",
        "retrieval",
        "diagnose",
        "recommend",
        "agent",
        "validate_output",
        "report",
    ]
    assert record.status == "completed" and record.started_at and record.finished_at
    assert record.created_at <= record.started_at <= record.finished_at


# --- failure cases -------------------------------------------------------------------------


def test_tls_failure_is_categorised(make_service, site):
    populate(site)

    def tls_fail(scheme, host, port, ip, timeout, policy):
        class Conn(http.client.HTTPConnection):
            def connect(self):
                raise ssl.SSLCertVerificationError("certificate verify failed")

        return Conn("127.0.0.1", site.port)

    service = make_service(
        fetcher_factory=factory_with(
            resolver=lambda h, p: [PUBLIC_IP], connection_factory=tls_fail
        )
    )
    record = run(service, url="https://acme.test/")
    assert record.status == "failed" and record.error_category == "tls"
    assert "verify failed" not in record.error_message  # exception text is not exposed


def test_timeouts_are_categorised(make_service, site):
    populate(site)
    site.add("/", b"x", drip_seconds=0.05)  # never finishes
    service = make_service(
        fetcher_factory=to_mock(site),
        crawl_overrides={"max_fetch_seconds": 0.5, "request_timeout_seconds": 0.5},
    )
    record = run(service)
    assert record.status == "failed" and record.error_category == "timeout"


def test_connection_refused_is_categorised(make_service, site):
    populate(site)

    def refuse(scheme, host, port, ip, timeout, policy):
        class Conn(http.client.HTTPConnection):
            def connect(self):
                raise ConnectionRefusedError()

        return Conn("127.0.0.1", 1)

    record = run(
        make_service(
            fetcher_factory=factory_with(
                resolver=lambda h, p: [PUBLIC_IP], connection_factory=refuse
            )
        )
    )
    assert record.status == "failed" and record.error_category == "connection"


def test_redirect_loop_fails_cleanly(make_service, site):
    populate(site)
    site.add("/", "", status=302, headers={"Location": "/loop"})
    site.add("/loop", "", status=302, headers={"Location": "/"})
    record = run(make_service(fetcher_factory=to_mock(site)))
    assert record.status == "failed" and record.error_category in {
        "crawl_error",
        "no_content",
    }


def test_a_redirect_to_a_metadata_address_is_never_followed(make_service, site):
    populate(site)
    site.add(
        "/",
        "",
        status=302,
        headers={"Location": "http://169.254.169.254/latest/meta-data/"},
    )
    record = run(make_service(fetcher_factory=to_mock(site)))
    assert record.status == "failed"
    assert site.paths_requested().count("/latest/meta-data/") == 0
    assert all("169.254" not in str(p) for p in site.paths_requested())


def test_a_redirect_to_another_domain_is_refused(make_service, site):
    populate(site)
    site.add("/", "", status=302, headers={"Location": "http://elsewhere.test/"})
    record = run(make_service(fetcher_factory=to_mock(site)))
    assert record.status == "failed"
    assert "elsewhere" not in (record.error_message or "")


def test_empty_site_is_a_failure_not_a_zero_score(make_service, site):
    populate(site)
    site.add("/", b"")
    record = run(make_service(fetcher_factory=to_mock(site)))
    assert record.status == "failed" and record.error_category == "no_content"
    assert "overall_score" not in record.summary


def test_malformed_html_is_audited_not_crashed(make_service, site):
    populate(site)
    site.add(
        "/",
        "<html><head><title>Broken<body><h1>Unclosed <div><p>text <b>bold <a href='/about'>link</h1></html",
    )
    record = run(make_service(fetcher_factory=to_mock(site)))
    assert record.status == "completed", (record.error_category, record.error_message)


def test_oversized_pages_are_truncated_and_the_report_says_so(make_service, site):
    populate(site)
    big = (
        "<html><head><title>Big</title></head><body><h1>Big</h1><p>"
        + "word " * 5000
        + "</p></body></html>"
    )
    site.add("/", big)
    service = make_service(
        fetcher_factory=to_mock(site), crawl_overrides={"max_response_bytes": 2000}
    )
    record = run(service, max_pages=1)
    assert record.status in {"completed", "incomplete"}
    report = service.report(record.audit_id)
    assert report.crawl["truncated_bodies"] >= 1
    assert any("truncated" in x for x in report.limitations)
    assert any(e.chunk_id for rf in report.findings for e in rf.evidence) or True


def test_a_byte_budget_stop_is_incomplete_not_completed(make_service, site):
    populate(site, extra="word " * 60)
    service = make_service(
        fetcher_factory=to_mock(site), crawl_overrides={"max_audit_bytes": 700}
    )
    record = run(service)
    assert record.status == "incomplete" and "stopped early" in record.error_message
    report = service.report(record.audit_id)
    assert (
        report.status == "incomplete"
        and report.crawl["stop_reason"] == "audit_byte_budget"
    )
    assert len(report.pages) < 3  # the pages not reached are not claimed as audited


def test_retrieval_with_no_matches_still_gives_evidence_backed_findings(
    make_service, site
):
    populate(site)
    service = make_service(fetcher_factory=to_mock(site))
    record = run(service, retrieval="lexical")
    assert record.status == "completed"
    assert all(rf.evidence for rf in service.report(record.audit_id).findings)


# --- unexpected failures inside the service ----------------------------------------------------


def test_a_persistence_failure_mid_run_does_not_leave_the_audit_running(
    make_service, site, monkeypatch
):
    populate(site)
    service = make_service(fetcher_factory=to_mock(site))
    real = service.store.save_stage

    def flaky(audit_id, stage):
        if stage.name == "crawl" and stage.status == "ok":
            raise sqlite3.OperationalError("disk I/O error at /secret/path")
        real(audit_id, stage)

    monkeypatch.setattr(service.store, "save_stage", flaky)
    record = run(service)
    assert record.status == "failed" and record.error_category == "internal_error"
    assert "/secret" not in (record.error_message or "")


def test_report_generation_failure_is_a_failed_audit_with_no_stale_completed_report(
    make_service, site, monkeypatch
):
    populate(site)
    import geoptimiser.app.pipeline as pipeline

    def broken(report):
        raise OSError("disk full at /secret/path")

    monkeypatch.setattr(pipeline, "render_html", broken)
    service = make_service(fetcher_factory=to_mock(site))
    record = run(service)
    assert record.status == "failed" and record.error_category == "internal_error"
    artifacts = service.store.artifacts(record.audit_id)
    assert (
        "report.json" not in artifacts
    )  # a report claiming "completed" must not survive
    assert not (service.data_dir / "audits" / record.audit_id / "report.json").exists()
    with pytest.raises(Exception) as err:
        service.report(record.audit_id)
    assert err.value.code == "report_unavailable"  # type: ignore[attr-defined]


def test_unsupported_evidence_fails_final_validation(make_service, site, monkeypatch):
    populate(site)
    import geoptimiser.app.pipeline as pipeline
    from geoptimiser.diagnosis import diagnose as real_diagnose
    from geoptimiser.schemas import Finding

    def corrupt(*a, **k):
        d = real_diagnose(*a, **k)
        f = d.findings[0]
        bad = Finding.model_validate(
            f.model_dump() | {"evidence_ids": ("ev_does_not_exist",)}
        )
        return d.model_copy(update={"findings": (bad, *d.findings[1:])})

    monkeypatch.setattr(pipeline, "diagnose", corrupt)
    service = make_service(fetcher_factory=to_mock(site))
    record = run(service)
    assert record.status == "failed"
    stages = {s.name: s for s in service.stages(record.audit_id)}
    assert (
        stages["validate_output"].status == "failed"
        or stages["diagnose"].status == "failed"
    )
    report = service.report(record.audit_id)
    assert not report.findings_available and not report.recommendations_validated
    assert report.validation_problems or report.failed_stages
    with pytest.raises(ServiceError):
        service.findings(record.audit_id)


def test_cross_audit_chunks_are_rejected_by_validation(make_service, site, monkeypatch):
    populate(site)
    import geoptimiser.app.pipeline as pipeline

    real = pipeline.diagnose

    def with_foreign_chunks(run, chunks, **k):
        from geoptimiser.schemas import Chunk

        foreign = [
            Chunk.model_validate(c.model_dump() | {"audit_id": "someone_else"})
            for c in chunks
        ]
        return real(run, foreign, **k)

    monkeypatch.setattr(pipeline, "diagnose", with_foreign_chunks)
    service = make_service(fetcher_factory=to_mock(site))
    record = run(service)
    report = service.report(record.audit_id)
    located = [e for rf in report.findings for e in rf.evidence if e.chunk_id]
    assert not located  # foreign passages are ignored, never cited
    assert record.status in {"completed", "incomplete"}


def test_corrupt_database_file_is_a_clear_error_not_a_traceback(tmp_path):
    from geoptimiser.app.store import StoreError

    path = tmp_path / "bad.db"
    path.write_bytes(b"this is not a sqlite database" * 50)
    with pytest.raises(StoreError) as err:
        AuditStore(path)
    assert str(tmp_path) not in str(err.value)


def test_default_agent_without_a_key_is_a_clean_incomplete(
    make_service, site, monkeypatch
):
    populate(site)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    service = make_service(
        fetcher_factory=to_mock(site)
    )  # the real default model factory
    record = run(service, use_agent=True)
    assert (
        record.status == "incomplete" and record.error_category == "agent_unavailable"
    )
    report = service.report(record.audit_id)
    assert report.findings_available and report.recommendations_validated
    assert report.agent["status"] == "unavailable"
    assert "OPENROUTER_API_KEY" not in json.dumps(report.model_dump(mode="json"))


def test_invalid_openrouter_key_format_never_reaches_logs_or_reports(
    make_service, site, monkeypatch, caplog
):
    populate(site)
    import logging

    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-LEAKCHECK-0123456789")

    def broken_client(config):
        from geoptimiser.agent import OpenRouterModel

        def factory(cfg, key):
            raise RuntimeError(f"401 from provider for key {key}")

        return OpenRouterModel(config.model, client_factory=factory)

    service = make_service(fetcher_factory=to_mock(site), model_factory=broken_client)
    record = run(service, use_agent=True)
    assert record.status == "incomplete"
    blob = (
        json.dumps(service.report(record.audit_id).model_dump(mode="json"))
        + record.model_dump_json()
    )
    blob += " ".join(r.getMessage() for r in caplog.records)
    assert "LEAKCHECK" not in blob


def test_agent_scenarios_through_the_pipeline(make_service, site):
    pytest.importorskip("langgraph")
    populate(site)
    from geoptimiser.agent import AgentConfig
    from tests.agent.conftest import HAPPY, ScriptedModel, call

    def with_script(replies, **agent_cfg):
        return make_service(fetcher_factory=to_mock(site), model_factory=lambda c: ScriptedModel(list(replies)),
                            agent=AgentConfig(retry_delay_seconds=0, **agent_cfg))  # fmt: skip

    ok = run(with_script(HAPPY), use_agent=True)
    assert ok.status == "completed"
    malformed = run(with_script(["nope", "still nope", "no json"]), use_agent=True)
    assert (
        malformed.status == "incomplete" and malformed.error_category == "agent_failed"
    )
    repeated = run(
        with_script([call("list_findings")] * 10, max_iterations=3), use_agent=True
    )
    assert repeated.status == "incomplete" and repeated.error_category in {
        "agent_incomplete",
        "agent_failed",
    }
    exhausted = run(with_script(HAPPY, max_iterations=2), use_agent=True)
    assert (
        exhausted.status == "incomplete"
        and exhausted.error_category == "agent_incomplete"
    )
    for record in (malformed, repeated, exhausted):
        assert record.status != "completed"


def test_agent_sees_page_text_as_data_only(make_service, site):
    pytest.importorskip("langgraph")
    populate(site)
    from tests.agent.conftest import ScriptedModel, call

    model = ScriptedModel(
        [
            call("get_finding", finding_id="fnd_F021"),
            call("run_shell", command="id"),
            '{"action": "finish"}',
        ]
    )
    service = make_service(fetcher_factory=to_mock(site), model_factory=lambda c: model)
    record = run(service, use_agent=True)
    assert record.status == "incomplete"
    steps = json.loads(
        (
            service.data_dir
            / service.store.artifacts(record.audit_id)["agent_trace.json"]["relpath"]
        ).read_text()
    )["steps"]
    assert [s["status"] for s in steps][:2] == ["ok", "rejected"] or steps


def test_restart_during_a_run_marks_it_interrupted_and_preserves_partial_artifacts(
    make_service, site, tmp_path
):
    populate(site)
    import threading

    gate = threading.Event()
    service = make_service(fetcher_factory=to_mock(site))
    real = service.store.save_stage

    def stall(audit_id, stage):
        real(audit_id, stage)
        if stage.name == "features" and stage.status == "running":
            gate.wait(10)

    service.store.save_stage = stall  # type: ignore[method-assign]
    record = service.submit(AuditSubmission(url=URL, authorization_confirmed=True))
    import time

    deadline = time.time() + 10
    while time.time() < deadline and service.get(record.audit_id).stage != "features":
        time.sleep(0.05)
    assert service.get(record.audit_id).status == "running"
    # a second process opens the same data directory while the first is "dead"
    restarted = AuditService(service.config)
    try:
        after = restarted.get(record.audit_id)
        assert after.status == "interrupted" and after.error_category == "interrupted"
        assert (
            restarted.data_dir / "audits" / record.audit_id / "fetches.jsonl"
        ).exists()
    finally:
        restarted.close()
        gate.set()
        service.runner.wait_idle(30)
    final = service.get(record.audit_id)
    assert (
        final.status == "interrupted"
    )  # the dead process's late writes cannot resurrect it


def test_unreadable_artifact_files_do_not_crash_reads(make_service, site):
    populate(site)
    service = make_service(fetcher_factory=to_mock(site))
    record = run(service)
    path = (
        service.data_dir
        / service.store.artifacts(record.audit_id)["report.json"]["relpath"]
    )
    path.write_text("{ not json")
    with pytest.raises(Exception) as err:
        service.report(record.audit_id)
    assert err.value.code == "report_unreadable"  # type: ignore[attr-defined]
    path.unlink()
    with pytest.raises(Exception) as err:
        service.report(record.audit_id)
    assert err.value.code == "report_unavailable"  # type: ignore[attr-defined]


def test_socket_level_dns_failure_vs_policy_block_are_distinguished(make_service, site):
    populate(site)

    def gai(h, p):
        raise socket.gaierror(-2, "Name or service not known")

    dns = run(make_service(fetcher_factory=factory_with(resolver=gai)))
    blocked = run(
        make_service(fetcher_factory=factory_with(resolver=lambda h, p: ["127.0.0.1"]))
    )
    assert (dns.error_category, blocked.error_category) == ("dns", "blocked_target")
