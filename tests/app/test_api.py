"""The HTTP API through FastAPI's test client. Skipped unless the ``api`` extra and
httpx are installed."""

import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

import warnings  # noqa: E402

with (
    warnings.catch_warnings()
):  # a third-party AnyIO/Starlette version mismatch warning
    warnings.filterwarnings(
        "ignore", message="The anyio.abc.BlockingPortal", category=DeprecationWarning
    )
    from fastapi.testclient import TestClient  # noqa: E402

from geoptimiser.app.api import create_app  # noqa: E402
from tests.app.conftest import populate  # noqa: E402

HOSTS = ("localhost", "127.0.0.1", "[::1]", "testserver")
BODY = {"url": "http://acme.test/", "authorization_confirmed": True}


@pytest.fixture
def client(make_service, site):
    populate(site)
    service = make_service(allowed_hosts=HOSTS)
    with TestClient(create_app(service)) as c:
        c.service = service  # type: ignore[attr-defined]
        yield c


def run_audit(client, **body):
    res = client.post("/api/v1/audits", json=BODY | body)
    assert res.status_code == 202, res.text
    assert client.service.runner.wait_idle(60)
    return res.json()["audit_id"]


def test_health_and_readiness(client):
    assert client.get("/api/v1/health").json() == {"status": "ok"}
    res = client.get("/api/v1/ready")
    assert res.status_code == 200 and res.json()["checks"] == {
        "database": True,
        "data_dir": True,
        "workers": True,
    }


def test_readiness_fails_when_the_database_is_unusable(client, monkeypatch):
    monkeypatch.setattr(
        client.service.store, "check", lambda: (_ for _ in ()).throw(RuntimeError("x"))
    )
    res = client.get("/api/v1/ready")
    assert res.status_code == 503 and res.json()["status"] == "not_ready"
    assert "x" not in res.text.replace("not_ready", "")


def test_the_whole_flow_from_url_to_persisted_report(client):
    res = client.post("/api/v1/audits", json=BODY)
    assert res.status_code == 202
    body = res.json()
    audit_id = body["audit_id"]
    assert res.headers["location"] == f"/api/v1/audits/{audit_id}"
    assert (
        body["status"] in {"queued", "running", "completed"} and body["links"]["report"]
    )
    assert client.service.runner.wait_idle(60)

    detail = client.get(f"/api/v1/audits/{audit_id}").json()
    assert detail["status"] == "completed" and detail["error_category"] is None
    assert {s["name"]: s["status"] for s in detail["stages"]}["crawl"] == "ok"
    assert (
        detail["summary"]["pages_ok"] == 3
        and detail["pipeline"]["catalog_version"] == 3
    )

    findings = client.get(f"/api/v1/audits/{audit_id}/findings").json()
    assert findings["count"] > 0 and all(f["evidence"] for f in findings["findings"])
    recs = client.get(f"/api/v1/audits/{audit_id}/recommendations").json()
    assert recs["count"] > 0 and all(
        r["verification_plan"] for r in recs["recommendations"]
    )

    report = client.get(f"/api/v1/audits/{audit_id}/report").json()
    assert report["status"] == "completed" and report["audit"]["audit_id"] == audit_id
    html = client.get(f"/api/v1/audits/{audit_id}/report.html")
    assert html.status_code == 200 and "text/html" in html.headers["content-type"]
    assert "default-src 'none'" in html.headers["content-security-policy"]
    assert "No change is guaranteed" in html.text
    assert '<meta http-equiv="Content-Security-Policy"' in html.text  # saved copies
    dl = client.get(f"/api/v1/audits/{audit_id}/report?download=true")
    assert "attachment" in dl.headers["content-disposition"]

    listing = client.get("/api/v1/audits").json()["audits"]
    assert [a["audit_id"] for a in listing] == [audit_id]


def test_unknown_malformed_and_traversal_ids(client):
    missing = client.get("/api/v1/audits/aud_" + "0" * 20)
    assert (
        missing.status_code == 404
        and missing.json()["error"]["code"] == "audit_not_found"
    )
    trailing_newline = "aud_" + "0" * 20 + "%0A"  # "$" in re.match accepts "\n"
    for bad in (
        "not-an-id",
        "aud_zz",
        "..%2F..%2Fetc%2Fpasswd",
        "aud_" + "0" * 21,
        trailing_newline,
    ):
        res = client.get(f"/api/v1/audits/{bad}")
        assert res.status_code in (400, 404), bad
        assert "/home" not in res.text and "Traceback" not in res.text
    res = client.get("/api/v1/audits/aud_" + "0" * 20 + "/report")
    assert res.status_code == 404 and "Traceback" not in res.text
    # the id check is a full match: a trailing newline is malformed, not "not found"
    res = client.get(f"/api/v1/audits/{trailing_newline}")
    assert res.status_code == 400 and res.json()["error"]["code"] == "invalid_audit_id"


def test_requests_are_validated_with_predictable_errors(client):
    cases = [
        ({"url": "http://acme.test/"}, 422),  # authorization missing
        ({"url": "", "authorization_confirmed": True}, 422),
        ({"url": "http://acme.test/", "authorization_confirmed": "yes"}, 422),
        (
            {"url": "http://acme.test/", "authorization_confirmed": True, "extra": 1},
            422,
        ),
        (
            {
                "url": "http://acme.test/",
                "authorization_confirmed": True,
                "options": {"max_pages": 10**6},
            },
            422,
        ),
        (
            {
                "url": "http://acme.test/",
                "authorization_confirmed": True,
                "options": {"retrieval": "web"},
            },
            422,
        ),
        ({"url": "http://localhost/", "authorization_confirmed": True}, 422),
        ({"url": "http://169.254.169.254/", "authorization_confirmed": True}, 422),
        ({"url": "file:///etc/passwd", "authorization_confirmed": True}, 422),
        ({"url": "http://acme.test/", "authorization_confirmed": False}, 422),
    ]
    for body, status in cases:
        res = client.post("/api/v1/audits", json=body)
        assert res.status_code == status, (body, res.text)
        err = res.json()["error"]
        assert err["code"] in {
            "invalid_request",
            "invalid_target",
            "authorization_required",
        }
        assert err["request_id"]
    res = client.post(
        "/api/v1/audits", json={"url": "x" * 5000, "authorization_confirmed": True}
    )
    assert (
        res.status_code in (413, 422) and "xxxxx" not in res.text
    )  # submitted values are not echoed
    assert (
        client.post(
            "/api/v1/audits",
            content=b"not json",
            headers={"content-type": "application/json"},
        ).status_code
        == 422
    )
    assert client.service.list_audits() == []  # nothing was created by invalid requests


def test_oversized_bodies_are_refused(client):
    res = client.post(
        "/api/v1/audits",
        content=b"{" + b" " * 40000 + b"}",
        headers={"content-type": "application/json"},
    )
    assert res.status_code == 413


def test_the_api_has_no_fetch_proxy_or_file_endpoint(client):
    paths = set(client.get("/api/v1/openapi.json").json()["paths"])
    assert paths == {
        "/api/v1/health", "/api/v1/ready", "/api/v1/audits", "/api/v1/audits/{audit_id}",
        "/api/v1/audits/{audit_id}/findings", "/api/v1/audits/{audit_id}/recommendations",
        "/api/v1/audits/{audit_id}/report", "/api/v1/audits/{audit_id}/report.html",
        "/api/v1/comparisons", "/api/v1/comparisons/{comparison_id}",
        # Read-only additions for the feature explorer: the shipped catalog (no input)
        # and one audit's stored feature results (id-validated, artifact-table lookup).
        "/api/v1/catalog", "/api/v1/audits/{audit_id}/features",
    }  # fmt: skip
    for path in (
        "/fetch",
        "/proxy",
        "/api/v1/fetch",
        "/files/../../etc/passwd",
        "/ui/../secret",
        "/ui/other.js",
    ):
        assert client.get(path).status_code in (404, 405)
    assert client.get("/docs").status_code == 404


def test_host_header_must_be_local(client):
    assert (
        client.get("/api/v1/health", headers={"host": "evil.example"}).status_code
        == 400
    )
    assert (
        client.get("/api/v1/health", headers={"host": "localhost:8000"}).status_code
        == 200
    )
    assert (
        client.get("/api/v1/health", headers={"host": "[::1]:8000"}).status_code == 200
    )
    # a bracketed IPv6 host without a port used to be mangled to "[::1]]" and refused
    assert client.get("/api/v1/health", headers={"host": "[::1]"}).status_code == 200
    assert client.get("/api/v1/health", headers={"host": "[::2]"}).status_code == 400


def test_security_headers_and_cors(client):
    res = client.get("/api/v1/health")
    assert (
        res.headers["x-content-type-options"] == "nosniff"
        and res.headers["x-frame-options"] == "DENY"
    )
    assert res.headers["cache-control"] == "no-store" and res.headers["x-request-id"]
    pre = client.options(
        "/api/v1/audits",
        headers={
            "origin": "http://evil.example",
            "access-control-request-method": "POST",
        },
    )
    assert "access-control-allow-origin" not in pre.headers  # no cross-origin access


def test_failed_audits_are_reported_as_failed_with_a_category(make_service, site):
    populate(site)
    site.add("/", "oops", status=503)
    service = make_service(allowed_hosts=HOSTS)
    with TestClient(create_app(service)) as c:
        audit_id = c.post("/api/v1/audits", json=BODY).json()["audit_id"]
        service.runner.wait_idle(60)
        detail = c.get(f"/api/v1/audits/{audit_id}").json()
        assert detail["status"] == "failed" and detail["error_category"] == "http_error"
        for sub in ("findings", "recommendations"):
            res = c.get(f"/api/v1/audits/{audit_id}/{sub}")
            assert res.status_code == 409 and res.json()["error"]["code"].endswith(
                "_unavailable"
            )
        report = c.get(f"/api/v1/audits/{audit_id}/report").json()
        assert report["status"] == "failed" and report["failed_stages"] == ["crawl"]


def test_queue_overflow_is_a_503_and_the_audit_is_not_left_queued(make_service, site):
    populate(site)
    import threading

    gate = threading.Event()
    service = make_service(allowed_hosts=HOSTS, max_queued=1, workers=1)
    service.runner.submit(lambda: gate.wait(10))
    import time

    time.sleep(0.2)
    service.runner.submit(lambda: None)  # fills the queue
    with TestClient(create_app(service)) as c:
        res = c.post("/api/v1/audits", json=BODY)
        assert res.status_code == 503 and res.json()["error"]["code"] == "queue_full"
        listed = c.get("/api/v1/audits").json()["audits"]
        # Changed by the security audit (queue-full rows finding): a refused submission
        # now leaves no durable audit row at all, instead of a 'failed' one.
        assert listed == []
    gate.set()


def test_compare_endpoints(client):
    first = run_audit(client)
    second = run_audit(client)
    res = client.post(
        "/api/v1/comparisons", json={"before_audit_id": first, "after_audit_id": second}
    )
    assert res.status_code == 200
    body = res.json()
    assert (
        body["statement"].startswith("These are differences")
        and body["before"]["audit_id"] == first
    )
    assert client.get(f"/api/v1/comparisons/{body['comparison_id']}").json() == body
    bad = client.post(
        "/api/v1/comparisons", json={"before_audit_id": second, "after_audit_id": first}
    )
    assert bad.status_code == 409 and bad.json()["error"]["code"] == "wrong_order"
    assert (
        client.post(
            "/api/v1/comparisons",
            json={"before_audit_id": first, "after_audit_id": first},
        ).status_code
        == 409
    )
    assert (
        client.post("/api/v1/comparisons", json={"before_audit_id": first}).status_code
        == 422
    )
    assert client.get("/api/v1/comparisons/cmp_" + "0" * 16).status_code == 404
    assert client.get("/api/v1/comparisons/..").status_code in (400, 404)


def test_unexpected_errors_are_generic(make_service, site, monkeypatch):
    populate(site)
    service = make_service(allowed_hosts=HOSTS)

    def boom(*a, **k):
        raise RuntimeError("secret /etc/shadow")

    monkeypatch.setattr(service, "list_audits", boom)
    with TestClient(create_app(service), raise_server_exceptions=False) as c:
        res = c.get("/api/v1/audits")
        assert (
            res.status_code == 500 and res.json()["error"]["code"] == "internal_error"
        )
        assert "secret" not in res.text and "shadow" not in res.text


def test_the_ui_is_served_from_three_fixed_files(client):
    for path, kind in (
        ("/", "text/html"),
        ("/ui/app.js", "javascript"),
        ("/ui/style.css", "text/css"),
    ):
        res = client.get(path)
        assert res.status_code == 200 and kind in res.headers["content-type"]
        assert "script-src 'self'" in res.headers["content-security-policy"]
    page = client.get("/").text
    js = client.get("/ui/app.js").text
    for forbidden in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
    ):
        assert forbidden not in js, forbidden
    assert "authorized" in page and '<script src="/ui/app.js">' in page
    assert "Math.random" not in client.get("/ui/app.js").text  # no fabricated values


def test_restart_keeps_audits_available_over_the_api(make_service, site):
    populate(site)
    service = make_service(allowed_hosts=HOSTS)
    with TestClient(create_app(service)) as c:
        audit_id = c.post("/api/v1/audits", json=BODY).json()["audit_id"]
        service.runner.wait_idle(60)
    again = make_service(allowed_hosts=HOSTS)
    with TestClient(create_app(again)) as c:
        assert c.get(f"/api/v1/audits/{audit_id}").json()["status"] == "completed"
        assert (
            c.get(f"/api/v1/audits/{audit_id}/report").json()["audit"]["audit_id"]
            == audit_id
        )


def test_no_secret_appears_in_any_response_or_report(client, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-SECRET-VALUE-123")
    audit_id = run_audit(client)
    blobs = [
        client.get(f"/api/v1/audits/{audit_id}{p}").text
        for p in ("", "/report", "/report.html", "/findings", "/recommendations")
    ]
    assert not any("SECRET-VALUE" in b for b in blobs)
    assert "sk-or" not in json.dumps(blobs)


def test_database_errors_become_generic_500s(make_service, site, monkeypatch):
    populate(site)
    import sqlite3

    service = make_service(allowed_hosts=HOSTS)

    def broken(*a, **k):
        raise sqlite3.OperationalError(
            "unable to open database file /home/user/secret/geoptimiser.db"
        )

    monkeypatch.setattr(service.store, "get_audit", broken)
    with TestClient(create_app(service), raise_server_exceptions=False) as c:
        res = c.get("/api/v1/audits/aud_" + "0" * 20)
        assert (
            res.status_code == 500 and res.json()["error"]["code"] == "internal_error"
        )
        assert "secret" not in res.text and "sqlite" not in res.text.lower()


def test_list_limit_is_clamped(client):
    run_audit(client)
    assert len(client.get("/api/v1/audits", params={"limit": -5}).json()["audits"]) == 1
    assert (
        len(client.get("/api/v1/audits", params={"limit": 10**9}).json()["audits"]) == 1
    )


def test_hostile_page_content_is_escaped_in_every_api_surface(make_service, site):
    populate(site)
    evil = "<img src=x onerror=alert(1)>"
    site.add(
        "/",
        f"<html><head><title>{evil}</title></head><body><h1>{evil}</h1><a href='/about'>a</a></body></html>",
    )
    service = make_service(allowed_hosts=HOSTS)
    with TestClient(create_app(service)) as c:
        audit_id = c.post("/api/v1/audits", json=BODY).json()["audit_id"]
        service.runner.wait_idle(60)
        page = c.get(f"/api/v1/audits/{audit_id}/report.html").text
        assert "<img" not in page and "onerror=alert" not in page.replace(
            "&lt;img src=x onerror=alert(1)&gt;", ""
        )
        assert (
            c.get(f"/api/v1/audits/{audit_id}/report.html")
            .headers["content-security-policy"]
            .startswith("default-src 'none'")
        )


def test_comparison_with_an_incomplete_or_failed_audit_is_a_409(make_service, site):
    populate(site)
    service = make_service(allowed_hosts=HOSTS)
    with TestClient(create_app(service)) as c:
        good = c.post("/api/v1/audits", json=BODY).json()["audit_id"]
        service.runner.wait_idle(60)
        site.add("/", "down", status=503)
        bad = c.post("/api/v1/audits", json=BODY).json()["audit_id"]
        service.runner.wait_idle(60)
        res = c.post(
            "/api/v1/comparisons", json={"before_audit_id": good, "after_audit_id": bad}
        )
        assert (
            res.status_code == 409
            and res.json()["error"]["code"] == "audit_not_completed"
        )
        other = c.post(
            "/api/v1/audits",
            json={"url": "http://other.test/", "authorization_confirmed": True},
        ).json()["audit_id"]
        service.runner.wait_idle(60)
        res = c.post(
            "/api/v1/comparisons",
            json={"before_audit_id": good, "after_audit_id": other},
        )
        assert res.status_code == 409


def test_ui_config_script_is_same_origin_by_default(client):
    res = client.get("/ui/config.js")
    assert res.status_code == 200 and "javascript" in res.headers["content-type"]
    assert res.text == 'window.GEOPTIMISER_CONFIG = {"apiBase": ""};\n'
    assert '<script src="/ui/config.js"></script>' in client.get("/").text


@pytest.fixture
def cors_client(make_service, site):
    populate(site)
    service = make_service(
        allowed_hosts=HOSTS,
        cors_origins=("http://127.0.0.1:8080",),
    )
    with TestClient(create_app(service)) as c:
        c.service = service  # type: ignore[attr-defined]
        yield c


def test_cors_allows_only_the_configured_loopback_origin(cors_client):
    origin = "http://127.0.0.1:8080"
    ok = cors_client.get("/api/v1/health", headers={"origin": origin})
    assert ok.headers["access-control-allow-origin"] == origin
    assert "access-control-allow-credentials" not in ok.headers
    for rejected_origin in (
        "https://evil.example",
        "https://geoptimiser.me",
        "https://geoptimiser.me.evil.example",
        "http://geoptimiser.me",
        "null",
    ):
        res = cors_client.get("/api/v1/health", headers={"origin": rejected_origin})
        assert "access-control-allow-origin" not in res.headers, rejected_origin


def test_cors_preflight_is_narrow(cors_client):
    origin = "http://127.0.0.1:8080"
    pre = cors_client.options(
        "/api/v1/audits",
        headers={
            "origin": origin,
            "access-control-request-method": "POST",
            "access-control-request-headers": "content-type",
        },
    )
    assert (
        pre.status_code == 200 and pre.headers["access-control-allow-origin"] == origin
    )
    assert set(
        pre.headers["access-control-allow-methods"].replace(" ", "").split(",")
    ) == {"GET", "POST"}
    allowed = {
        h.strip()
        for h in pre.headers["access-control-allow-headers"].lower().split(",")
    }
    assert "content-type" in allowed and not allowed - {
        "accept",
        "accept-language",
        "content-language",
        "content-type",
    }
    bad = cors_client.options(
        "/api/v1/audits",
        headers={
            "origin": origin,
            "access-control-request-method": "DELETE",
        },
    )
    assert bad.status_code == 400
    evil = cors_client.options(
        "/api/v1/audits",
        headers={
            "origin": "https://evil.example",
            "access-control-request-method": "POST",
        },
    )
    assert "access-control-allow-origin" not in evil.headers


def test_cross_origin_flow_still_enforces_host_and_validation(cors_client):
    origin = "http://127.0.0.1:8080"
    headers = {"origin": origin, "host": "127.0.0.1"}
    res = cors_client.post(
        "/api/v1/audits",
        json={"url": "http://localhost/", "authorization_confirmed": True},
        headers=headers,
    )
    assert (
        res.status_code == 422 and res.headers["access-control-allow-origin"] == origin
    )
    created = cors_client.post("/api/v1/audits", json=BODY, headers=headers)
    assert created.status_code == 202 and "location" in created.headers
    cors_client.service.runner.wait_idle(60)
    rejected = cors_client.get(
        "/api/v1/health",
        headers={"origin": origin, "host": "evil.example"},
    )
    assert rejected.status_code == 400
    assert rejected.headers["access-control-allow-origin"] == origin


def test_cors_configuration_is_validated():
    from pydantic import ValidationError

    from geoptimiser.app import AppConfig

    for bad in (
        "*",
        "http://geoptimiser.me",
        "https://geoptimiser.me/path",
        "https://u@geoptimiser.me",
        'https://a"b',
    ):
        with pytest.raises(ValidationError):
            AppConfig(data_dir=".", cors_origins=(bad,))
    with pytest.raises(ValidationError):
        AppConfig(data_dir=".", cors_origins=("https://geoptimiser.me/",))
    assert AppConfig(
        data_dir=".", cors_origins=("http://127.0.0.1:8080/",)
    ).cors_origins == ("http://127.0.0.1:8080",)
    assert AppConfig(data_dir=".").cors_origins == ()


def test_catalog_describes_all_features_with_levels(client):
    res = client.get("/api/v1/catalog")
    assert res.status_code == 200
    data = res.json()
    ids = [f["feature_id"] for f in data["features"]]
    assert ids == [f"F{n:03d}" for n in range(1, 121)]
    f110 = next(f for f in data["features"] if f["feature_id"] == "F110")
    assert f110["implementation_status"] == "implemented"
    assert f110["validation"]["implementation_level"] == "IMPLEMENTED"
    assert f110["validation"]["validation_level"] in {
        "UNIT_TESTED",
        "PIPELINE_VALIDATED",
    }
    f111 = next(f for f in data["features"] if f["feature_id"] == "F111")
    assert f111["validation"]["validation_level"] == "NOT_TESTED"
    f005 = next(f for f in data["features"] if f["config_keys"])
    assert set(f005["config_defaults"]) <= set(f005["config_keys"])


def test_features_endpoint_shows_stored_results_or_refuses(client):
    assert client.get("/api/v1/audits/not-an-id/features").status_code == 400
    assert client.get("/api/v1/audits/aud_" + "0" * 20 + "/features").status_code == 404


def test_ui_fonts_are_fixed_files_and_nothing_else_is_served(client):
    for path in ("/ui/hanken-grotesk.woff2", "/ui/jetbrains-mono.woff2"):
        res = client.get(path)
        assert res.status_code == 200
        assert res.headers["content-type"] == "font/woff2"
        assert res.content[:4] == b"wOF2"
    assert "SIL Open Font License" in client.get("/ui/FONTS-LICENSE.txt").text
    # No directory serving: neighbouring package files are not reachable.
    for path in ("/ui/", "/ui/../api.py", "/ui/api.py", "/ui/index.html.bak"):
        assert client.get(path).status_code == 404


def test_agent_audits_are_rate_limited_server_side(make_service, site):
    populate(site)
    service = make_service(allowed_hosts=HOSTS, max_agent_audits_per_hour=1)
    with TestClient(create_app(service)) as c:
        body = {**BODY, "options": {**BODY.get("options", {}), "use_agent": True}}
        first = c.post("/api/v1/audits", json=body)
        assert first.status_code == 202
        second = c.post("/api/v1/audits", json=body)
        assert second.status_code == 429
        assert second.json()["error"]["code"] == "agent_rate_limited"
        # Audits without the agent are not affected.
        assert c.post("/api/v1/audits", json=BODY).status_code == 202
    service.runner.wait_idle(30)


def test_agent_rate_limit_zero_forbids_agent_audits(make_service, site):
    populate(site)
    service = make_service(allowed_hosts=HOSTS, max_agent_audits_per_hour=0)
    with TestClient(create_app(service)) as c:
        body = {**BODY, "options": {**BODY.get("options", {}), "use_agent": True}}
        assert c.post("/api/v1/audits", json=body).status_code == 429
        assert c.get("/api/v1/audits").json()["audits"] == []
