"""Every validation fixture, replayed through the real application layer.

The validation harness (``geoptimiser.validation.runner``) drives the crawler, the
extractor and the feature engine directly. The product, however, runs audits through
``AuditService`` -> ``run_pipeline`` and shows them through the HTTP API. This test runs
each pre-declared fixture through that whole path and checks, through the API that the
frontend reads (``/api/v1/audits/{id}/features`` and ``/report``):

1. every page- and site-scope feature expectation written in the fixture's spec, and
2. that the per-feature results are identical to the harness's results, so nothing
   between the feature engine and the browser changes a measured status.

A feature whose fixture expectations pass here is ``PIPELINE_VALIDATED`` in the
validation matrix (geoptimiser.validation.matrix).
"""

import http.client
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from geoptimiser.app import AppConfig, AuditService, PipelineDeps  # noqa: E402
from geoptimiser.app.api import create_app  # noqa: E402
from geoptimiser.app.models import AuditOptions, AuditSubmission  # noqa: E402
from geoptimiser.crawler import SafeFetcher  # noqa: E402
from geoptimiser.validation.levels import APP_PIPELINE_NO_FEATURES  # noqa: E402
from geoptimiser.validation.runner import _PUBLIC_IP, ServedSite, run_fixture  # noqa: E402
from geoptimiser.validation.spec import load_fixtures  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
SPECS = load_fixtures(FIXTURES)


def _path(url: str | None) -> str | None:
    if url is None:
        return None
    rest = url.split("://", 1)[-1]
    return "/" + rest.split("/", 1)[1] if "/" in rest else "/"


@pytest.mark.parametrize("spec", SPECS, ids=[s.id for s in SPECS])
def test_fixture_through_app_pipeline(spec, tmp_path: Path) -> None:
    site = ServedSite(spec)
    try:

        def connect(scheme, host, port, ip, timeout, policy):  # noqa: ANN001
            return http.client.HTTPConnection("127.0.0.1", site.port, timeout=timeout)

        def factory(config, store, audit_id, allowed):  # noqa: ANN001
            return SafeFetcher(
                config, store, audit_id, host_allowed=allowed,
                resolver=lambda h, p: [_PUBLIC_IP], connection_factory=connect,
            )  # fmt: skip

        crawl = spec.crawl
        config = AppConfig(
            data_dir=tmp_path / "data",
            max_pages_cap=100,
            max_depth_cap=5,
            agent_enabled=False,
            crawl_overrides={
                "max_response_bytes": crawl.max_response_bytes,
                "request_timeout_seconds": crawl.request_timeout_seconds,
                "max_fetch_seconds": max(crawl.request_timeout_seconds * 2, 2.0),
                "min_request_interval_seconds": 0,
                "respect_robots": crawl.respect_robots,
            },
        )
        service = AuditService(
            config, deps=PipelineDeps(fetcher_factory=factory, sleep=lambda s: None)
        )
        try:
            record = service.submit(
                AuditSubmission(
                    url="https://fixture.test/",
                    authorization_confirmed=True,
                    options=AuditOptions(
                        max_pages=crawl.max_pages,
                        max_depth=crawl.max_depth,
                        retrieval="lexical",
                    ),
                )
            )
            service.runner.wait_idle()
            client = TestClient(create_app(service), base_url="http://127.0.0.1")
            audit = client.get(f"/api/v1/audits/{record.audit_id}").json()
            assert audit["status"] in {"completed", "incomplete", "failed"}
            features = client.get(f"/api/v1/audits/{record.audit_id}/features")
        finally:
            service.close()
    finally:
        site.close()

    if spec.id in APP_PIPELINE_NO_FEATURES:
        # Nothing auditable was fetched: the audit fails at the crawl stage and the
        # API says the feature results are unavailable instead of inventing any.
        assert audit["status"] == "failed"
        assert audit["error_category"] is not None
        assert features.status_code == 409
        return
    assert features.status_code == 200, features.text
    data = features.json()
    by_feature = {f["feature_id"]: f for f in data["features"]}
    assert len(by_feature) == 120

    # 1. The fixture's own pre-declared expectations, read back through the API.
    for path, expectations in spec.expect.pages.items():
        for fid, exp in expectations.items():
            hits = [r for r in by_feature[fid]["results"] if _path(r["url"]) == path]
            assert hits, f"{spec.id}: no {fid} result for {path} through the API"
            assert hits[0]["status"] == exp.status, (
                f"{spec.id} {path} {fid}: expected {exp.status}, API shows {hits[0]['status']}"
            )
    for fid, exp in spec.expect.site.items():
        statuses = {r["status"] for r in by_feature[fid]["results"]}
        assert exp.status in statuses, f"{spec.id} site {fid}: {statuses}"

    # 2. The application path must not change what the feature engine measured.
    direct = run_fixture(spec, tmp_path / "direct")
    expected = sorted(
        (r.feature_id, _path(r.subject_url), r.status) for r in direct.run.results
    )
    shown = sorted(
        (fid, _path(r["url"]), r["status"])
        for fid, f in by_feature.items()
        for r in f["results"]
    )
    assert shown == expected
