import http.client
import socket
import time
from collections.abc import Callable
from typing import Any

import pytest

from geoptimiser.crawler import CrawlConfig, LocalBodyStore, SafeFetcher, StorageError
from geoptimiser.crawler.netguard import is_public_address
from tests.crawler.conftest import MockSite

PUBLIC_IP = "93.184.216.34"
Make = Callable[..., SafeFetcher]


class Seam:
    """Pretends names resolve to public IPs while really talking to the mock.

    The default (real) IP policy therefore validates the resolved addresses, and
    ``connections`` records every address the fetcher tried to connect to.
    """

    def __init__(self, site: MockSite) -> None:
        self.site = site
        self.connections: list[tuple[str, str, str]] = []
        self.lookups: list[str] = []
        self.dns: dict[str, list[str]] = {}

    def resolver(self, host: str, port: int) -> list[str]:
        self.lookups.append(host)
        return self.dns.get(host, [PUBLIC_IP])

    def factory(
        self, scheme: str, host: str, port: int, ip: str, timeout: float, policy: Any
    ) -> http.client.HTTPConnection:
        self.connections.append((scheme, host, ip))
        return http.client.HTTPConnection("127.0.0.1", self.site.port, timeout=timeout)


@pytest.fixture
def seam(site: MockSite) -> Seam:
    return Seam(site)


@pytest.fixture
def public_fetcher(
    seam: Seam, store: LocalBodyStore, make_config: Callable[..., CrawlConfig]
) -> Callable[..., SafeFetcher]:
    def build(**config: object) -> SafeFetcher:
        return SafeFetcher(
            make_config(**config),
            store,
            "aud_test",
            resolver=seam.resolver,
            ip_policy=is_public_address,
            connection_factory=seam.factory,
        )

    return build


# --- successful and unsuccessful responses ------------------------------------


def test_success_stores_body_by_reference(
    site: MockSite, make_fetcher: Make, store: LocalBodyStore
) -> None:
    site.add("/", "<html>hello</html>", headers={"Set-Cookie": "sid=1", "X-Other": "1"})

    result = make_fetcher().fetch(site.url())
    record = result.record

    assert record.outcome == "success" and record.status_code == 200
    assert record.audit_id == "aud_test" and record.schema_version == 1
    assert record.body is not None and not record.body.truncated
    assert store.get(record.body.ref) == b"<html>hello</html>" == result.body
    assert "hello" not in record.model_dump_json()  # the body is never inline
    assert record.headers["content-type"].startswith("text/html")
    assert record.headers["content-length"] == "18"
    assert "set-cookie" not in record.headers  # credential headers never persist
    assert "x-other" not in record.headers  # allow-list only
    assert record.completed_at >= record.started_at


def test_request_is_minimal_and_anonymous(site: MockSite, make_fetcher: Make) -> None:
    site.add("/", "<html></html>")
    make_fetcher().fetch(site.url())

    sent = site.requests[0][1]
    assert sent["accept-encoding"] == "identity"
    assert sent["user-agent"].startswith("GeoptimiserBot/")
    assert not {"cookie", "authorization", "referer"} & sent.keys()


def test_chunked_response_is_read(site: MockSite, make_fetcher: Make) -> None:
    body = "<html>" + "x" * 450 + "</html>"
    site.add("/", body, chunked=True)

    result = make_fetcher().fetch(site.url())
    assert result.body == body.encode()


@pytest.mark.parametrize("status", [404, 410, 500, 503])
def test_http_errors_record_status_and_do_not_store(
    site: MockSite, make_fetcher: Make, status: int
) -> None:
    site.add("/", "<html>error page</html>", status=status)

    record = make_fetcher().fetch(site.url()).record
    assert record.outcome == "http_error" and record.status_code == status
    assert record.body is None
    assert record.body_not_stored_reason == "non_success_status"


@pytest.mark.parametrize("status", [200, 204])
def test_empty_body_is_distinct_from_unstored(
    site: MockSite, make_fetcher: Make, status: int
) -> None:
    site.add("/", b"", status=status)

    record = make_fetcher().fetch(site.url()).record
    assert record.outcome == "success" and record.body is None
    assert record.body_not_stored_reason == "empty_response"


@pytest.mark.parametrize("content_type", ["application/pdf", "image/png", None])
def test_non_html_is_not_downloaded(
    site: MockSite, make_fetcher: Make, content_type: str | None
) -> None:
    site.add("/", b"%PDF-1.7 ...", content_type=content_type)

    record = make_fetcher().fetch(site.url()).record
    assert record.body is None
    assert record.body_not_stored_reason == "unsupported_content_type"


def test_content_type_parameters_and_case_are_accepted(
    site: MockSite, make_fetcher: Make
) -> None:
    site.add("/", "<p>x", content_type="Text/HTML; Charset=ISO-8859-1")
    assert make_fetcher().fetch(site.url()).record.body is not None


def test_compressed_responses_are_not_stored(
    site: MockSite, make_fetcher: Make
) -> None:
    site.add("/", b"\x1f\x8b\x08...", headers={"Content-Encoding": "gzip"})

    record = make_fetcher().fetch(site.url()).record
    assert record.body is None
    assert record.body_not_stored_reason == "unsupported_content_encoding"


# --- size limits enforced while streaming -------------------------------------


def test_oversized_body_is_truncated_and_flagged(
    site: MockSite, make_fetcher: Make, make_config: Callable[..., CrawlConfig]
) -> None:
    site.add("/", "a" * 10_000)

    result = make_fetcher(make_config(max_response_bytes=1000)).fetch(site.url())
    body = result.record.body
    assert body is not None and body.truncated and body.size_bytes == 1000
    assert result.body == b"a" * 1000


def test_body_exactly_at_the_limit_is_not_truncated(
    site: MockSite, make_fetcher: Make, make_config: Callable[..., CrawlConfig]
) -> None:
    site.add("/", "a" * 1000)

    body = (
        make_fetcher(make_config(max_response_bytes=1000)).fetch(site.url()).record.body
    )
    assert body is not None and not body.truncated and body.size_bytes == 1000


def test_endless_stream_is_cut_off_while_reading(
    site: MockSite, make_fetcher: Make, make_config: Callable[..., CrawlConfig]
) -> None:
    site.add("/", endless=True)  # no Content-Length, never ends

    started = time.monotonic()
    record = (
        make_fetcher(make_config(max_response_bytes=50_000)).fetch(site.url()).record
    )
    assert record.body is not None and record.body.truncated
    assert record.body.size_bytes == 50_000
    assert time.monotonic() - started < 5


def test_huge_declared_content_length_cannot_exceed_the_limit(
    site: MockSite, make_fetcher: Make, make_config: Callable[..., CrawlConfig]
) -> None:
    site.add("/", endless=True, headers={"Content-Length": "1000000000"})

    record = make_fetcher(make_config(max_response_bytes=100)).fetch(site.url()).record
    assert record.body is not None and record.body.truncated
    assert record.body.size_bytes == 100


def test_caller_can_lower_the_limit_but_not_raise_it(
    site: MockSite, make_fetcher: Make, make_config: Callable[..., CrawlConfig]
) -> None:
    site.add("/", "a" * 5000)
    fetcher = make_fetcher(make_config(max_response_bytes=1000))

    assert fetcher.fetch(site.url(), max_bytes=200).record.body.size_bytes == 200  # type: ignore[union-attr]
    assert fetcher.fetch(site.url(), max_bytes=10**9).record.body.size_bytes == 1000  # type: ignore[union-attr]


# --- timeouts and transport failures ------------------------------------------


def test_slow_drip_hits_the_total_fetch_deadline(
    site: MockSite, make_fetcher: Make, make_config: Callable[..., CrawlConfig]
) -> None:
    site.add("/", drip_seconds=0.05)  # each read succeeds; the whole never ends

    started = time.monotonic()
    record = make_fetcher(make_config(max_fetch_seconds=0.6)).fetch(site.url()).record
    assert record.outcome == "transport_error" and record.error_type == "timeout"
    assert record.status_code is None and record.body is None
    assert time.monotonic() - started < 5


def test_connection_refused_is_a_transport_error(
    site: MockSite, make_fetcher: Make, make_config: Callable[..., CrawlConfig]
) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        closed_port = sock.getsockname()[1]
    config = make_config(allowed_ports=frozenset({closed_port}))

    record = make_fetcher(config).fetch(f"http://site.test:{closed_port}/").record
    assert record.outcome == "transport_error" and record.error_type == "connection"


def test_dns_failure_is_recorded(site: MockSite, make_fetcher: Make) -> None:
    def resolver(host: str, port: int) -> list[str]:
        raise socket.gaierror("Name or service not known")

    record = make_fetcher(resolver=resolver).fetch(site.url()).record
    assert record.error_type == "dns"


def test_invalid_url_is_a_caller_error(make_fetcher: Make) -> None:
    for bad in ["not a url", "ftp://example.com/", "file:///etc/passwd", ""]:
        with pytest.raises(ValueError):
            make_fetcher().fetch(bad)


# --- SSRF: the initial target -------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "[::1]",
        "10.1.2.3",
        "169.254.169.254",
        "2130706433",
        "0x7f.1",
        "0.0.0.0",
    ],
)
def test_private_literal_targets_are_never_contacted(
    site: MockSite, public_fetcher: Make, seam: Seam, host: str
) -> None:
    site.add("/", "secret")

    record = public_fetcher().fetch(f"http://{host}:{site.port}/").record
    assert record.error_type == "blocked_address"
    assert record.outcome == "transport_error"
    assert seam.connections == [] and site.requests == []


def test_hostname_resolving_to_private_address_is_refused(
    site: MockSite, public_fetcher: Make, seam: Seam
) -> None:
    seam.dns["internal.test"] = ["10.0.0.5"]

    record = public_fetcher().fetch(f"http://internal.test:{site.port}/").record
    assert record.error_type == "blocked_address"
    assert seam.connections == []


def test_mixed_public_and_private_answers_are_refused(
    site: MockSite, public_fetcher: Make, seam: Seam
) -> None:
    seam.dns["mixed.test"] = [PUBLIC_IP, "127.0.0.1"]

    record = public_fetcher().fetch(f"http://mixed.test:{site.port}/").record
    assert record.error_type == "blocked_address" and seam.connections == []


def test_disallowed_port_is_refused_before_resolving(
    site: MockSite, public_fetcher: Make, seam: Seam
) -> None:
    record = public_fetcher().fetch("http://site.test:22/").record
    assert record.error_type == "blocked_port"
    assert seam.lookups == []


def test_credentials_in_url_are_refused(site: MockSite, public_fetcher: Make) -> None:
    record = public_fetcher().fetch(f"http://user:pw@site.test:{site.port}/").record
    assert record.error_type == "blocked_url"
    assert "pw" not in (record.error_message or "")


# --- SSRF: DNS rebinding and the connected peer -------------------------------


def test_connection_uses_the_vetted_address_and_resolves_once(
    site: MockSite, public_fetcher: Make, seam: Seam
) -> None:
    site.add("/", "<html>ok</html>")
    answers = iter([[PUBLIC_IP], ["127.0.0.1"], ["127.0.0.1"]])  # rebinding attacker
    seam.resolver = lambda host, port: next(answers)  # type: ignore[method-assign]

    record = public_fetcher().fetch(site.url()).record
    assert record.outcome == "success"
    assert seam.connections == [("http", "site.test", PUBLIC_IP)]


def test_rebinding_after_a_redirect_is_blocked(
    site: MockSite, public_fetcher: Make, seam: Seam
) -> None:
    site.add("/", status=302, headers={"Location": f"http://evil.test:{site.port}/x"})
    site.add("/x", "internal")
    seam.dns["evil.test"] = ["192.168.0.10"]

    record = public_fetcher().fetch(site.url()).record
    assert record.outcome == "redirect_not_followed"
    assert record.redirect_refusal_reason == "blocked_address"
    assert record.status_code == 302 and record.body is None
    assert site.paths_requested() == ["/"]
    assert all(ip == PUBLIC_IP for _, _, ip in seam.connections)


def test_peer_address_is_rechecked_after_connecting(
    site: MockSite, store: LocalBodyStore, make_config: Callable[..., CrawlConfig]
) -> None:
    site.add("/", "<html>ok</html>")
    calls: list[str] = []

    def policy(ip: Any) -> bool:
        calls.append(str(ip))
        return len(calls) == 1  # accepts the resolved address, rejects the peer

    fetcher = SafeFetcher(
        make_config(),
        store,
        "aud_test",
        resolver=lambda h, p: ["127.0.0.1"],
        ip_policy=policy,
    )
    record = fetcher.fetch(site.url()).record
    assert record.error_type == "blocked_address"
    assert len(calls) == 2 and site.requests == []


# --- redirects ----------------------------------------------------------------


def test_same_site_redirect_chain_is_followed_and_recorded(
    site: MockSite, make_fetcher: Make
) -> None:
    site.add("/a", status=301, headers={"Location": "/b"})
    site.add("/b", status=302, headers={"Location": f"{site.url('/c')}"})
    site.add("/c", "<html>done</html>")

    record = make_fetcher().fetch(site.url("/a")).record
    assert record.outcome == "success"
    assert str(record.final_url) == site.url("/c")
    assert [(h.status_code, h.location) for h in record.redirects] == [
        (301, "/b"),
        (302, site.url("/c")),
    ]
    assert [str(h.url) for h in record.redirects] == [site.url("/a"), site.url("/b")]


def test_too_many_redirects_keeps_the_hops(
    site: MockSite, make_fetcher: Make, make_config: Callable[..., CrawlConfig]
) -> None:
    for i in range(10):
        site.add(f"/{i}", status=302, headers={"Location": f"/{i + 1}"})

    record = make_fetcher(make_config(max_redirects=3)).fetch(site.url("/0")).record
    assert record.error_type == "too_many_redirects"
    assert len(record.redirects) == 4 and record.status_code is None


def test_redirect_loop_is_detected(site: MockSite, make_fetcher: Make) -> None:
    site.add("/a", status=302, headers={"Location": "/b"})
    site.add("/b", status=302, headers={"Location": "/a"})

    record = make_fetcher().fetch(site.url("/a")).record
    assert record.error_type == "too_many_redirects"
    assert site.paths_requested().count("/a") <= 2


def test_zero_redirects_allowed_means_first_redirect_is_an_error(
    site: MockSite, make_fetcher: Make, make_config: Callable[..., CrawlConfig]
) -> None:
    site.add("/a", status=302, headers={"Location": "/b"})
    record = make_fetcher(make_config(max_redirects=0)).fetch(site.url("/a")).record
    assert record.error_type == "too_many_redirects"


@pytest.mark.parametrize(
    ("location", "reason"),
    [
        ("http://127.0.0.1:{port}/admin", "blocked_address"),
        ("http://[::1]:{port}/admin", "blocked_address"),
        ("http://169.254.169.254:{port}/latest/meta-data", "blocked_address"),
        ("http://2130706433:{port}/", "blocked_address"),
        ("http://site.test:22/", "blocked_port"),
        ("http://user:pw@site.test:{port}/", "credentials_in_url"),
        ("ftp://site.test/", "invalid_location"),
        ("file:///etc/passwd", "invalid_location"),
        ("javascript:alert(1)", "invalid_location"),
    ],
)
def test_unsafe_redirect_targets_are_refused_without_connecting(
    site: MockSite, public_fetcher: Make, seam: Seam, location: str, reason: str
) -> None:
    site.add("/", status=302, headers={"Location": location.format(port=site.port)})

    record = public_fetcher().fetch(site.url()).record
    assert record.outcome == "redirect_not_followed"
    assert record.redirect_refusal_reason == reason
    assert record.status_code == 302
    assert site.paths_requested() == ["/"]
    assert seam.connections == [("http", "site.test", PUBLIC_IP)]


def test_missing_location_is_refused(site: MockSite, make_fetcher: Make) -> None:
    site.add("/", status=302)
    record = make_fetcher().fetch(site.url()).record
    assert record.outcome == "redirect_not_followed"
    assert record.redirect_refusal_reason == "missing_location"


@pytest.mark.parametrize("status", [300, 304, 305])
def test_non_redirect_3xx_is_not_a_redirect(
    site: MockSite, make_fetcher: Make, status: int
) -> None:
    site.add("/", status=status, headers={"Location": "/x"})  # even with a Location
    record = make_fetcher().fetch(site.url()).record
    assert record.outcome == "redirect_not_followed"
    assert record.redirect_refusal_reason == "not_a_redirect"
    assert site.paths_requested() == ["/"]


def test_https_to_http_downgrade_is_refused(
    site: MockSite, public_fetcher: Make, seam: Seam
) -> None:
    # The seam serves "https" over plain HTTP; only the redirect logic is under test.
    site.add(
        "/", status=301, headers={"Location": f"http://site.test:{site.port}/next"}
    )
    site.add("/next", "plaintext")

    record = public_fetcher().fetch(f"https://site.test:{site.port}/").record
    assert record.outcome == "redirect_not_followed"
    assert record.redirect_refusal_reason == "https_downgrade"
    assert site.paths_requested() == ["/"]


def test_cross_domain_redirect_is_refused_when_scoped(
    site: MockSite, make_fetcher: Make
) -> None:
    site.add("/", status=301, headers={"Location": f"http://other.test:{site.port}/x"})
    site.add("/x", "elsewhere")
    fetcher = make_fetcher(host_allowed=lambda host: host == "site.test")

    record = fetcher.fetch(site.url()).record
    assert record.redirect_refusal_reason == "cross_domain"
    assert site.paths_requested() == ["/"]


def test_https_url_requires_a_verified_certificate(
    site: MockSite, store: LocalBodyStore, make_config: Callable[..., CrawlConfig]
) -> None:
    # The mock speaks plain HTTP, so a real TLS handshake must fail, not be skipped.
    fetcher = SafeFetcher(
        make_config(),
        store,
        "aud_test",
        resolver=lambda h, p: ["127.0.0.1"],
        ip_policy=lambda ip: ip.is_loopback,
    )
    record = fetcher.fetch(f"https://site.test:{site.port}/").record
    assert record.outcome == "transport_error"
    assert record.error_type in {"tls", "connection"}


# --- incomplete responses (premature EOF) ----------------------------------------


def test_server_closing_before_content_length_is_a_transport_failure(
    site: MockSite, make_fetcher: Make
) -> None:
    site.add("/", "<html>only 26 bytes</html>", content_length=1000)

    result = make_fetcher().fetch(site.url())
    record = result.record
    assert record.outcome == "transport_error"
    assert record.error_type == "incomplete_response"
    assert "26 of 1000" in (record.error_message or "")
    assert record.body is None and result.body is None


def test_cut_chunked_response_is_a_transport_failure(
    site: MockSite, make_fetcher: Make
) -> None:
    site.add("/", "<html>cut", cut_chunked=True)

    record = make_fetcher().fetch(site.url()).record
    assert record.outcome == "transport_error"
    assert record.error_type == "incomplete_response"


def test_matching_content_length_is_complete(
    site: MockSite, make_fetcher: Make
) -> None:
    site.add("/", "<html>whole</html>")
    body = make_fetcher().fetch(site.url()).record.body
    assert body is not None and not body.truncated


def test_intentional_truncation_is_not_an_incomplete_response(
    site: MockSite, make_fetcher: Make, make_config: Callable[..., CrawlConfig]
) -> None:
    site.add("/", "a" * 5000)  # honest Content-Length larger than the limit
    record = make_fetcher(make_config(max_response_bytes=100)).fetch(site.url()).record
    assert record.outcome == "success"
    assert record.body is not None and record.body.truncated


def test_chunked_response_without_content_length_is_complete(
    site: MockSite, make_fetcher: Make
) -> None:
    site.add("/", "<html>" + "x" * 300 + "</html>", chunked=True)
    assert make_fetcher().fetch(site.url()).record.outcome == "success"


# --- Location handling ---------------------------------------------------------------


def test_long_location_is_followed_in_full(site: MockSite, make_fetcher: Make) -> None:
    long_path = "/" + "a" * 2040  # past the 2000-char header record cap
    site.add("/", status=301, headers={"Location": long_path})
    site.add(long_path, "<html>long</html>")

    record = make_fetcher().fetch(site.url()).record
    assert record.outcome == "success"
    assert str(record.final_url).endswith(long_path)
    assert record.redirects[0].location == long_path  # raw, not truncated


def test_oversized_location_is_refused(site: MockSite, make_fetcher: Make) -> None:
    site.add("/", status=301, headers={"Location": "/" + "a" * 9000})
    record = make_fetcher().fetch(site.url()).record
    assert record.redirect_refusal_reason == "invalid_location"


def test_conflicting_location_headers_are_refused(
    site: MockSite, make_fetcher: Make
) -> None:
    site.add("/", status=302, raw_headers=[("Location", "/a"), ("Location", "/b")])
    site.add("/a", "a")
    record = make_fetcher().fetch(site.url()).record
    assert record.redirect_refusal_reason == "invalid_location"
    assert site.paths_requested() == ["/"]


def test_identical_duplicate_location_headers_are_followed(
    site: MockSite, make_fetcher: Make
) -> None:
    site.add("/", status=302, raw_headers=[("Location", "/a"), ("Location", "/a")])
    site.add("/a", "<html>a</html>")
    assert make_fetcher().fetch(site.url()).record.outcome == "success"


def test_redirect_allowed_hook_can_refuse_before_connecting(
    site: MockSite, make_fetcher: Make
) -> None:
    site.add("/", status=301, headers={"Location": "/next"})
    site.add("/next", "<html>x</html>")
    asked: list[str] = []

    def hook(url: str) -> bool:
        asked.append(url)
        return False

    record = make_fetcher().fetch(site.url(), redirect_allowed=hook).record
    assert record.redirect_refusal_reason == "robots_disallowed"
    assert asked == [site.url("/next")]
    assert site.paths_requested() == ["/"]


# --- storage failures and argument checks ---------------------------------------------


def test_storage_failure_is_not_reported_as_a_network_error(
    site: MockSite, make_fetcher: Make, store: LocalBodyStore
) -> None:
    site.add("/", "<html>x</html>")

    def broken_put(data: bytes, *, truncated: bool = False):  # type: ignore[no-untyped-def]
        raise OSError(28, "No space left on device")

    store.put = broken_put  # type: ignore[method-assign]
    with pytest.raises(StorageError, match="could not store body"):
        make_fetcher().fetch(site.url())


@pytest.mark.parametrize("bad", [0, -5])
def test_max_bytes_must_be_positive(make_fetcher: Make, bad: int) -> None:
    with pytest.raises(ValueError, match="max_bytes"):
        make_fetcher().fetch("http://site.test:1/", max_bytes=bad)
