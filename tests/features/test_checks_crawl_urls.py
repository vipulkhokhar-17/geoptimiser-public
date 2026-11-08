"""Categories A and B."""

import pytest

from tests.features.builders import (
    FETCH_404,
    FETCH_REFUSED,
    FETCH_TIMEOUT,
    audit,
    page,
    robots_file,
    run,
    status_of,
    statuses,
)

HOME = "https://www.example.com/"
A = "https://www.example.com/a"
B = "https://www.example.com/b"
C = "https://www.example.com/c"
D = "https://www.example.com/d"
E = "https://www.example.com/e"


# --- A: crawlability ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("fetch", "expected"),
    [
        ({}, "pass"),
        (FETCH_404, "fail"),
        (FETCH_REFUSED, "not_measured"),
        (FETCH_TIMEOUT, "not_measured"),
    ],
    ids=["200", "404", "redirect-refused", "timeout"],
)
def test_f001_http_success(fetch: dict, expected: str) -> None:
    assert status_of("F001", page(HOME, fetch=fetch)) == expected


def test_f001_failure_cites_the_status_and_url() -> None:
    result = run("F001", audit(page(HOME, fetch=FETCH_404)))[0]
    assert result.status == "fail" and result.severity == "high"
    assert result.observed_value == 404 and result.subject_url == HOME
    assert result.evidence[0].source_url == HOME and "404" in result.evidence[0].snippet


def test_f001_does_not_treat_a_missing_response_as_a_failure() -> None:
    result = run("F001", audit(page(HOME, fetch=FETCH_TIMEOUT)))[0]
    assert result.status == "not_measured" and result.observed_value is None


def test_f002_crawlable_links() -> None:
    assert status_of("F002", page(HOME, doc={"links": [A]})) == "pass"
    assert status_of("F002", page(HOME, doc={"links": []})) == "fail"
    assert (
        status_of("F002", page(HOME, doc={"links": [A]}), min_crawlable_links=2)
        == "fail"
    )


def test_f003_robots_accessibility_per_origin() -> None:
    cases = {200: "pass", 404: "pass", 503: "fail"}
    for code, expected in cases.items():
        inputs = audit(
            page(HOME), robots=(robots_file("User-agent: *\n", status=code),)
        )
        assert run("F003", inputs)[0].status == expected, code
    timeout = audit(page(HOME), robots=(robots_file(None, outcome="transport_error"),))
    assert run("F003", timeout)[0].status == "not_measured"


def test_f003_not_measured_when_robots_was_never_fetched() -> None:
    result = run("F003", audit(page(HOME)))[0]
    assert result.status == "not_measured" and result.scope == "site"


def test_f004_robots_policy() -> None:
    def status(text: str | None, **kw: object) -> str:
        robots = (robots_file(text, **kw),) if text is not None or kw else ()
        return run("F004", audit(page(HOME), robots=robots))[0].status

    assert status("User-agent: *\nAllow: /\n") == "pass"
    # A block is an owner policy: reported as a warning to confirm, never a failure.
    assert status("User-agent: GPTBot\nDisallow: /\n") == "warning"
    assert status("User-agent: *\nDisallow: /\n") == "warning"
    assert status(None, status=404) == "pass"  # absent robots.txt allows everything
    assert status(None, status=503) == "not_measured"
    assert status(None) == "not_measured"  # no robots.txt fetched at all


def test_f004_names_the_blocked_agents_and_cites_robots_txt() -> None:
    robots = robots_file(
        "User-agent: GPTBot\nDisallow: /\nUser-agent: ClaudeBot\nDisallow: /a\n"
    )
    result = run("F004", audit(page(A), robots=(robots,)))[0]
    assert result.status == "warning"
    assert "confirm intent" in (result.explanation or "")
    assert result.observed_value == ["GPTBot", "ClaudeBot"]
    assert result.evidence[0].source_url == "https://www.example.com/robots.txt"


def test_f004_uses_wildcards_and_longest_match() -> None:
    robots = robots_file("User-agent: GPTBot\nDisallow: /*.pdf$\nAllow: /docs/a.pdf\n")
    inputs = audit(page("https://www.example.com/docs/a.pdf"), robots=(robots,))
    assert (
        run("F004", inputs)[0].status == "pass"
    )  # the longer Allow beats the wildcard Disallow


@pytest.mark.parametrize(
    ("meta", "expected"),
    [
        (None, "pass"),
        ("index, follow", "pass"),
        ("nofollow", "pass"),
        ("noindex, follow", "warning"),
        ("NONE", "warning"),
        ("max-snippet:0, noindex", "warning"),
    ],
)
def test_f005_meta_robots(meta: str | None, expected: str) -> None:
    assert status_of("F005", page(HOME, doc={"meta_robots": meta})) == expected


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, "pass"),
        ("nofollow", "pass"),
        ("noindex", "warning"),
        ("googlebot: noindex", "warning"),
        ("noarchive, none", "warning"),
    ],
)
def test_f006_x_robots_tag(header: str | None, expected: str) -> None:
    headers = {"Content-Type": "text/html"} | (
        {"X-Robots-Tag": header} if header else {}
    )
    assert status_of("F006", page(HOME, fetch={"headers": headers})) == expected


def test_f006_not_measured_without_a_response() -> None:
    assert status_of("F006", page(HOME, fetch=FETCH_TIMEOUT)) == "not_measured"


def test_f007_sitemap_declared_is_never_a_failure() -> None:
    declared = robots_file(
        "User-agent: *\nSitemap: https://www.example.com/sitemap.xml\n"
    )
    result = run("F007", audit(page(HOME), robots=(declared,)))[0]
    assert result.status == "pass" and result.observed_value == [
        "https://www.example.com/sitemap.xml"
    ]
    undeclared = robots_file("User-agent: *\nAllow: /\n")
    assert (
        run("F007", audit(page(HOME), robots=(undeclared,)))[0].status == "not_measured"
    )
    assert run("F007", audit(page(HOME)))[0].status == "not_measured"


def graph_site():  # type: ignore[no-untyped-def]
    return audit(
        page(HOME, doc={"links": [A, B]}),
        page(A, doc={"links": [C, HOME]}),
        page(B, doc={"links": []}),
        page(C, doc={"links": [D]}),
        page(D, doc={"links": [E]}),
        page(E, doc={"links": []}),
        page("https://www.example.com/lost", doc={"links": [A]}),
    )


def test_f009_orphan_risk_and_f072_incoming_links() -> None:
    inputs = graph_site()
    orphan = statuses("F009", inputs)
    assert orphan[HOME] == "not_applicable"  # entry page
    assert orphan[A] == "pass" and orphan[C] == "pass"
    assert orphan["https://www.example.com/lost"] == "fail"
    incoming = statuses("F072", inputs)
    assert incoming["https://www.example.com/lost"] == "fail" and incoming[A] == "pass"
    assert statuses("F072", inputs, min_incoming_links=2)[B] == "fail"


def test_orphan_failure_cites_the_page() -> None:
    result = next(r for r in run("F009", graph_site()) if r.status == "fail")
    assert result.evidence[0].source_url == "https://www.example.com/lost"
    assert result.observed_value == 0


def test_f010_crawl_depth() -> None:
    inputs = graph_site()
    depth = statuses("F010", inputs)
    assert depth[HOME] == "pass" and depth[C] == "pass"  # 2 clicks
    assert depth[D] == "pass"  # 3 clicks, at the limit
    assert depth[E] == "fail"  # 4 clicks
    assert depth["https://www.example.com/lost"] == "not_measured"  # unreachable
    assert statuses("F010", inputs, max_click_depth=1)[C] == "fail"


def test_graph_follows_redirects_to_the_final_url() -> None:
    old, new = "https://www.example.com/old", "https://www.example.com/new"
    redirected = page(
        old,
        fetch={
            "final_url": new,
            "redirects": [{"url": old, "status_code": 301, "location": "/new"}],
        },
    )
    inputs = audit(page(HOME, doc={"links": [old]}), redirected)
    assert statuses("F009", inputs)[new] == "pass"
    assert statuses("F010", inputs)[new] == "pass"


# --- B: URL health -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("canonical", "expected"),
    [(HOME, "pass"), (None, "fail"), ("", "fail"), ("   ", "fail")],
)
def test_f011_canonical_presence(canonical: str | None, expected: str) -> None:
    assert status_of("F011", page(HOME, doc={"canonical_url": canonical})) == expected


def test_f012_canonical_validity() -> None:
    def status(canonical: str | None, *extra) -> str:  # type: ignore[no-untyped-def]
        return run("F012", audit(page(HOME, doc={"canonical_url": canonical}), *extra))[
            0
        ].status

    assert status(None) == "not_applicable"
    # Resolves to an absolute URL, but the target was not crawled: reachability is
    # unknown, which is not_measured, never a pass (docs/validation, A2).
    assert status("/relative-ok") == "not_measured"
    assert status("mailto:a@b.c") == "fail"
    assert status("https://www.example.com/x#frag") == "fail"
    assert status(A, page(A, fetch=FETCH_404)) == "fail"
    assert status(A, page(A, doc={"meta_robots": "noindex"})) == "fail"
    assert status(A, page(A)) == "pass"


def test_f012_states_when_the_target_was_not_crawled() -> None:
    result = run("F012", audit(page(HOME, doc={"canonical_url": "/elsewhere"})))[0]
    assert result.status == "not_measured"
    assert "not crawled" in (result.explanation or "")


def test_f013_canonical_consistency() -> None:
    def status(home_canonical, *others):  # type: ignore[no-untyped-def]
        return run(
            "F013", audit(page(HOME, doc={"canonical_url": home_canonical}), *others)
        )[0].status

    assert status(HOME) == "pass"
    assert status(None) == "not_applicable"
    assert status(A) == "not_measured"  # target not crawled
    assert status(A, page(A, doc={"canonical_url": A})) == "pass"
    assert status(A, page(A, doc={"canonical_url": B})) == "fail"  # chain
    assert status(A, page(A, doc={"canonical_url": HOME})) == "fail"  # loop


def test_f014_duplicate_content_cites_both_pages() -> None:
    same = "Identical body text about pricing and plans. " * 5
    inputs = audit(
        page(HOME, doc={"text": same}),
        page(A, doc={"text": same.upper()}),  # case/whitespace-insensitive
        page(
            B,
            doc={
                "text": "Completely different text about something else entirely. " * 5
            },
        ),
        page(C, doc={"text": "short"}),
    )
    result = {r.subject_url: r for r in run("F014", inputs)}
    assert result[HOME].status == "fail" and result[A].status == "fail"
    assert result[B].status == "pass" and result[C].status == "not_applicable"
    cited = {e.source_url for e in result[HOME].evidence}
    assert cited == {HOME, A}


def test_f015_redirect_chain_length() -> None:
    def hops(n: int) -> dict:
        urls = [f"https://www.example.com/r{i}" for i in range(n + 1)]
        return {
            "requested_url": urls[0],
            "final_url": urls[-1],
            "redirects": [
                {"url": urls[i], "status_code": 301, "location": urls[i + 1]}
                for i in range(n)
            ],
        }

    # No redirect: nothing to judge, so not applicable (as F016), not a free pass.
    assert status_of("F015", page(HOME)) == "not_applicable"
    assert (
        status_of("F015", page("https://www.example.com/r0", fetch=hops(1))) == "pass"
    )
    assert (
        status_of("F015", page("https://www.example.com/r0", fetch=hops(3))) == "fail"
    )
    assert (
        status_of(
            "F015",
            page("https://www.example.com/r0", fetch=hops(3)),
            max_redirect_hops=3,
        )
        == "pass"
    )


def test_f016_redirect_loop() -> None:
    a, b = "https://www.example.com/a", "https://www.example.com/b"
    loop = {
        "outcome": "transport_error",
        "status_code": None,
        "final_url": None,
        "headers": {},
        "body": None,
        "error_type": "too_many_redirects",
        "error_message": "loop",
        "redirects": [
            {"url": a, "status_code": 302, "location": "/b"},
            {"url": b, "status_code": 302, "location": "/a"},
        ],
    }
    assert status_of("F016", page(a, fetch=loop)) == "fail"
    chain = {
        "final_url": "https://www.example.com/c",
        "redirects": [{"url": a, "status_code": 301, "location": "/c"}],
    }
    assert status_of("F016", page(a, fetch=chain)) == "pass"
    assert status_of("F016", page(HOME)) == "not_applicable"


def test_f017_broken_internal_links_and_f079_concentration() -> None:
    inputs = audit(
        page(HOME, doc={"links": [A, B, C]}),
        page(A, fetch=FETCH_404),
        page(B, doc={"links": [A]}),
        page(C, doc={"links": []}),
        page(
            "https://www.example.com/lonely",
            doc={"links": ["https://www.example.com/uncrawled"]},
        ),
    )
    broken = statuses("F017", inputs)
    assert broken[HOME] == "fail" and broken[B] == "fail"
    assert broken[C] == "not_measured"  # no links at all
    assert (
        broken["https://www.example.com/lonely"] == "not_measured"
    )  # target never crawled
    assert A not in broken or broken[A] == "not_measured"  # error page has no document
    site = run("F079", inputs)[0]
    assert site.status == "fail" and site.observed_value["total_broken"] == 2
    assert site.observed_value["pages_affected"] == 2 and site.scope == "site"


def test_f079_passes_only_when_targets_were_checked() -> None:
    healthy = audit(page(HOME, doc={"links": [A]}), page(A))
    assert run("F079", healthy)[0].status == "pass"
    nothing = audit(page(HOME, doc={"links": []}))
    assert run("F079", nothing)[0].status == "not_measured"


def test_f018_url_parameters() -> None:
    assert status_of("F018", page(HOME)) == "pass"
    assert status_of("F018", page("https://www.example.com/p?a=1&b=2&c=3")) == "pass"
    assert (
        status_of("F018", page("https://www.example.com/p?a=1&b=2&c=3&d=4")) == "fail"
    )
    result = run(
        "F018", audit(page(HOME, doc={"links": ["https://www.example.com/x?y=1"]}))
    )[0]
    assert result.observed_value["internal_links_with_query"] == 1


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/", "not_applicable"),
        ("/pricing/plans", "pass"),
        ("/blog/my-first-post.html", "pass"),
        ("/p/3f2504e0-4f89-11d3-9a0c-0305e82c3301", "fail"),
        ("/item/8723647823648", "fail"),
        ("/x/" + "a" * 70, "fail"),
        ("/2024/05/guide", "pass"),
    ],
)
def test_f019_url_readability(path: str, expected: str) -> None:
    assert status_of("F019", page("https://www.example.com" + path)) == expected


def test_f020_https_consistency() -> None:
    assert status_of("F020", page(HOME)) == "pass"
    assert status_of("F020", page("http://www.example.com/")) == "fail"
    insecure = page(
        HOME, doc={"links": ["http://www.example.com/old", "http://other.org/"]}
    )
    result = run("F020", audit(insecure))[0]
    assert (
        result.status == "fail"
        and result.observed_value["insecure_internal_links"] == 1
    )
    assert status_of("F020", page(HOME, fetch=FETCH_TIMEOUT)) == "not_measured"
