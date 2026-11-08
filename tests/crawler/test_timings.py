"""Fetch timings: what is measured is real, what is not says so (ADR-0024)."""

from collections.abc import Callable

from geoptimiser.crawler import SafeFetcher
from tests.crawler.conftest import MockSite, TlsMaterials
from tests.crawler.test_fetcher import Seam
from tests.crawler.test_tls import trusting

Make = Callable[..., SafeFetcher]


def test_plain_http_measures_dns_connect_ttfb_and_total(
    site: MockSite, make_fetcher: Make
):
    site.add("/", "<html>hi</html>")
    record = make_fetcher().fetch(site.url("/")).record
    t = record.timings
    assert t is not None and record.outcome == "success"
    assert t.dns_ms is not None and t.connect_ms is not None
    assert t.ttfb_ms is not None and t.response_ms is not None
    assert t.ttfb_ms <= t.response_ms <= t.total_ms
    assert t.tls_ms is None and "plain HTTP" in t.unmeasured["tls_ms"]
    assert set(t.unmeasured) == {"tls_ms"}


def test_https_measures_the_tls_handshake(
    tls_site: MockSite, tls_materials: TlsMaterials, make_config, store
):
    tls_site.add("/", "<html>secure</html>")
    fetcher = SafeFetcher(
        make_config(allowed_ports=frozenset({tls_site.port})),
        store,
        "aud_t",
        resolver=lambda h, p: ["127.0.0.1"],
        ip_policy=lambda ip: ip.is_loopback,
        ssl_context=trusting(tls_materials.ca),
    )
    t = fetcher.fetch(f"https://site.test:{tls_site.port}/").record.timings
    assert t is not None and t.tls_ms is not None and t.tls_ms > 0
    assert t.connect_ms is not None and t.unmeasured == {}


def test_ip_literal_has_no_dns_measurement(site: MockSite, make_fetcher: Make):
    site.add("/", "<html>hi</html>")
    t = make_fetcher().fetch(f"http://127.0.0.1:{site.port}/").record.timings
    assert t is not None and t.dns_ms is None
    assert "IP literal" in t.unmeasured["dns_ms"]


def test_a_custom_transport_that_exposes_nothing_reports_not_measured(
    site: MockSite, make_config, store
):
    seam = Seam(site)
    site.add("/", "<html>hi</html>")
    fetcher = SafeFetcher(
        make_config(),
        store,
        "aud_t",
        resolver=seam.resolver,
        connection_factory=seam.factory,
    )
    t = fetcher.fetch(site.url("/")).record.timings
    assert t is not None and t.dns_ms is not None and t.ttfb_ms is not None
    assert t.connect_ms is None and "not exposed" in t.unmeasured["connect_ms"]


def test_failures_keep_what_was_measured_and_never_invent_the_rest(
    site: MockSite, make_fetcher: Make
):
    def failing(host: str, port: int) -> list[str]:
        raise __import__("socket").gaierror("no such host")

    record = (
        make_fetcher(resolver=failing).fetch(site.url("/", host="missing.test")).record
    )
    assert record.outcome == "transport_error" and record.error_type == "dns"
    t = record.timings
    assert t is not None and t.dns_ms is not None  # time spent before the failure
    assert t.connect_ms is None and t.ttfb_ms is None and t.response_ms is None
    assert all(r for r in t.unmeasured.values())


def test_redirects_report_the_final_exchange_and_whole_fetch_total(
    site: MockSite, make_fetcher: Make
):
    site.add("/a", "", status=302, headers={"Location": "/b"})
    site.add("/b", "<html>b</html>")
    record = make_fetcher().fetch(site.url("/a")).record
    t = record.timings
    assert len(record.redirects) == 1 and t is not None
    assert t.total_ms >= t.response_ms  # total spans both hops


def test_timings_round_trip_through_json(site: MockSite, make_fetcher: Make):
    from geoptimiser.schemas import FetchRecord

    site.add("/", "<html>hi</html>")
    record = make_fetcher().fetch(site.url("/")).record
    assert FetchRecord.model_validate_json(record.model_dump_json()) == record


def test_old_records_without_timings_still_load():
    from geoptimiser.schemas import FetchRecord

    data = {
        "schema_version": 1, "audit_id": "a", "fetch_id": "f",
        "requested_url": "https://x.test/", "outcome": "transport_error",
        "error_type": "dns", "error_message": "x",
        "started_at": "2026-01-01T00:00:00Z", "completed_at": "2026-01-01T00:00:01Z",
    }  # fmt: skip
    assert FetchRecord.model_validate(data).timings is None
