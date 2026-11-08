"""Regression tests for the crawler findings of security audit run 1.

Each test reproduces the confirmed (or validated) defect against the real code path and
asserts the fixed behaviour. See docs/project/SECURITY_REVIEW.md.
"""

import time

import pytest

from geoptimiser.crawler import Crawler
from geoptimiser.crawler.robots import RobotsPolicy, parse_rules
from geoptimiser.crawler.urls import host_in_scope, normalize_url
from tests.crawler.conftest import MockSite
from tests.crawler.test_crawl import Make, MakeConfig, audit_request, page_paths, run

UA = "GeoptimiserBot"


def norm(url: str) -> str | None:
    return normalize_url(url, max_length=2048, follow_query=False)


# --- urls.normalize_url: WHATWG/urlsplit host differential -----------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://evil.test\\@site.test/",  # browsers read host evil.test
        "http://evil.test\\.site.test/",
        "http://site%2etest/",  # percent-encoded host
        "http://evil%2etest%40site.test/",
        "http://exa mple.test/",
    ],
)
def test_ambiguous_hosts_are_rejected(url: str) -> None:
    assert norm(url) is None


def test_unicode_hosts_are_converted_to_ascii_before_scoping() -> None:
    normalized = norm("http://bücher.site.test/") or ""
    assert "xn--bcher-kva.site.test" in normalized
    assert host_in_scope("xn--bcher-kva.site.test", "site.test")


def test_ordinary_urls_still_normalize() -> None:
    assert (norm("HTTP://Site.Test/a#frag") or "").startswith("http://site.test/a")


# --- fetcher: the first hop is scope-checked, not only redirects -----------------


def test_out_of_scope_first_hop_is_refused_without_a_request(
    site: MockSite, make_fetcher: Make
) -> None:
    fetcher = make_fetcher(host_allowed=lambda host: host == "site.test")
    record = fetcher.fetch(site.url(host="other.test")).record
    assert record.outcome == "transport_error"
    assert record.error_type == "blocked_url"
    assert site.requests == []


# --- crawl: one bad discovered link no longer aborts the audit -------------------


def test_backslash_link_is_not_followed_and_the_crawl_completes(
    site: MockSite, make_fetcher: Make, make_config: MakeConfig
) -> None:
    site.add(
        "/",
        f'<a href="http://evil.test\\@site.test:{site.port}/x">x</a><a href="/a">a</a>',
        headers={"Content-Type": "text/html"},
    )
    site.add("/a", "<p>a</p>", headers={"Content-Type": "text/html"})
    result = run(site, make_fetcher, make_config(max_depth=2))
    assert result.stop_reason == "completed"
    assert page_paths(result) == ["/", "/a"]
    assert "/x" not in site.paths_requested()


def test_uncanonicalizable_url_is_skipped_not_fatal(
    site: MockSite, make_fetcher: Make, make_config: MakeConfig, monkeypatch
) -> None:
    site.add("/", "<p>home</p>", headers={"Content-Type": "text/html"})
    config = make_config()
    fetcher = make_fetcher(config, host_allowed=lambda h: host_in_scope(h, "site.test"))
    real = fetcher.fetch
    calls = {"n": 0}

    def flaky(url: str, **kwargs: object):
        calls["n"] += 1
        if kwargs.get("kind", "page") == "page":
            raise ValueError("cannot canonicalize")
        return real(url, **kwargs)

    monkeypatch.setattr(fetcher, "fetch", flaky)
    result = Crawler(audit_request(), config, fetcher, seed_url=site.url()).run()
    assert [s.reason for s in result.skipped] == ["invalid_url"]
    assert calls["n"] >= 1


# --- robots: parse cost is linear in the file, not groups x agent lines ---------


def test_many_user_agent_groups_parse_quickly_and_keep_only_relevant_rules() -> None:
    other = "".join(
        f"User-agent: bot{i}\nDisallow: /p{i}\n" for i in range(20_000)
    )  # ~450 KB, under the robots size limit
    text = other + f"User-agent: {UA}\nDisallow: /mine\n"
    start = time.perf_counter()
    rules = parse_rules(text, UA)
    assert time.perf_counter() - start < 2.0
    robots = RobotsPolicy(rules)
    assert not robots.allows("https://x.test/mine")
    assert robots.allows("https://x.test/p5")


def test_wildcard_group_is_used_only_without_a_specific_group() -> None:
    text = "User-agent: *\nDisallow: /all\n\nUser-agent: other\nDisallow: /o\n"
    robots = RobotsPolicy(parse_rules(text, UA))
    assert not robots.allows("https://x.test/all")
    assert robots.allows("https://x.test/o")
