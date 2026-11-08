"""Local TLS tests: real handshakes against a throw-away CA (no network access)."""

import ssl
from collections.abc import Callable

import pytest

from geoptimiser.crawler import CrawlConfig, LocalBodyStore, SafeFetcher
from tests.crawler.conftest import MockSite, TlsMaterials, loopback_only


def trusting(ca_file: object) -> ssl.SSLContext:
    return ssl.create_default_context(cafile=str(ca_file))


@pytest.fixture
def tls_fetcher(
    tls_site: MockSite,
    store: LocalBodyStore,
    make_config: Callable[..., CrawlConfig],
) -> Callable[..., SafeFetcher]:
    """Fetcher for the TLS site: every name resolves to loopback."""

    def build(context: ssl.SSLContext | None) -> SafeFetcher:
        return SafeFetcher(
            make_config(allowed_ports=frozenset({tls_site.port})),
            store,
            "aud_test",
            resolver=lambda host, port: ["127.0.0.1"],
            ip_policy=loopback_only,
            ssl_context=context,
        )

    return build


def test_trusted_ca_and_matching_hostname_succeeds(
    tls_site: MockSite,
    tls_materials: TlsMaterials,
    tls_fetcher: Callable[..., SafeFetcher],
) -> None:
    tls_site.add("/", "<html>over tls</html>")

    result = tls_fetcher(trusting(tls_materials.ca)).fetch(
        f"https://site.test:{tls_site.port}/"
    )

    assert result.record.outcome == "success"
    assert result.body == b"<html>over tls</html>"
    assert tls_site.requests[0][1]["host"] == f"site.test:{tls_site.port}"


def test_hostname_mismatch_is_rejected(
    tls_site: MockSite,
    tls_materials: TlsMaterials,
    tls_fetcher: Callable[..., SafeFetcher],
) -> None:
    tls_site.add("/", "<html>secret</html>")

    # Same server and a trusted CA, but the certificate is for site.test only.
    record = (
        tls_fetcher(trusting(tls_materials.ca))
        .fetch(f"https://other.test:{tls_site.port}/")
        .record
    )

    assert record.outcome == "transport_error" and record.error_type == "tls"
    assert tls_site.requests == []  # no HTTP request was sent over the bad session


def test_untrusted_ca_is_rejected(
    tls_site: MockSite,
    tls_materials: TlsMaterials,
    tls_fetcher: Callable[..., SafeFetcher],
) -> None:
    tls_site.add("/", "<html>x</html>")

    record = (
        tls_fetcher(trusting(tls_materials.other_ca))
        .fetch(f"https://site.test:{tls_site.port}/")
        .record
    )

    assert record.outcome == "transport_error" and record.error_type == "tls"
    assert tls_site.requests == []


def test_default_context_does_not_trust_the_test_ca(
    tls_site: MockSite, tls_fetcher: Callable[..., SafeFetcher]
) -> None:
    tls_site.add("/", "<html>x</html>")

    record = tls_fetcher(None).fetch(f"https://site.test:{tls_site.port}/").record

    assert record.outcome == "transport_error" and record.error_type == "tls"


def test_https_to_http_downgrade_is_still_refused_over_real_tls(
    tls_site: MockSite,
    tls_materials: TlsMaterials,
    tls_fetcher: Callable[..., SafeFetcher],
) -> None:
    tls_site.add(
        "/", status=301, headers={"Location": f"http://site.test:{tls_site.port}/x"}
    )

    record = (
        tls_fetcher(trusting(tls_materials.ca))
        .fetch(f"https://site.test:{tls_site.port}/")
        .record
    )

    assert record.redirect_refusal_reason == "https_downgrade"
    assert tls_site.paths_requested() == ["/"]


# --- an injected context cannot weaken verification ---


def insecure(check_hostname: bool, verify_mode: ssl.VerifyMode) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = check_hostname
    context.verify_mode = verify_mode
    return context


@pytest.mark.parametrize(
    "context",
    [
        insecure(False, ssl.CERT_NONE),
        insecure(False, ssl.CERT_REQUIRED),
        insecure(False, ssl.CERT_OPTIONAL),
    ],
    ids=["no_verification", "no_hostname_check", "optional_certificate"],
)
def test_non_verifying_contexts_are_refused(
    store: LocalBodyStore,
    make_config: Callable[..., CrawlConfig],
    context: ssl.SSLContext,
) -> None:
    with pytest.raises(ValueError, match="must verify"):
        SafeFetcher(make_config(), store, "aud_test", ssl_context=context)


def test_ssl_context_cannot_be_combined_with_a_custom_factory(
    store: LocalBodyStore, make_config: Callable[..., CrawlConfig]
) -> None:
    with pytest.raises(ValueError, match="custom factory"):
        SafeFetcher(
            make_config(),
            store,
            "aud_test",
            ssl_context=ssl.create_default_context(),
            connection_factory=lambda *args: None,  # type: ignore[arg-type,return-value]
        )
