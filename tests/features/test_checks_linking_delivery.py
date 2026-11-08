"""Category H (beyond the graph tests) and K."""

from datetime import timedelta

from geoptimiser.schemas import Heading
from tests.features.builders import (
    FETCH_TIMEOUT,
    NOW,
    audit,
    page,
    run,
    status_of,
    statuses,
)

HOME = "https://www.example.com/"
A = "https://www.example.com/a"
B = "https://www.example.com/b"


def test_f071_internal_link_density_is_informational_and_cited() -> None:
    doc = {"text": "x" * 2000, "links": [A, B, "https://other.org/"]}
    result = run("F071", audit(page(HOME, doc=doc), page(A), page(B)))[0]
    assert result.status == "pass" and result.observed_value == 1.0  # 2 per 2000 chars
    assert status_of("F071", page(HOME, doc={"text": ""})) == "not_applicable"


def test_f073_outgoing_links_split_internal_and_external() -> None:
    doc = {"links": [A, B, "https://other.org/x", "https://sub.example.com/y"]}
    result = run("F073", audit(page(HOME, doc=doc)))[0]
    assert result.observed_value == {
        "internal": 3,
        "external": 1,
    }  # subdomains are internal


def test_f080_topic_redundancy_between_similar_pages() -> None:
    def labelled(title: str, h1: str) -> dict:
        return {"title": title, "headings": [Heading(level=1, text=h1)]}

    inputs = audit(
        page(
            HOME,
            doc=labelled(
                "Email marketing automation tools", "Email marketing automation"
            ),
        ),
        page(
            A,
            doc=labelled(
                "Email marketing automation tools overview",
                "Email marketing automation",
            ),
        ),
        page(B, doc=labelled("Company history and founders", "Our founders")),
    )
    result = run("F080", inputs)[0]
    assert result.status == "fail" and result.is_heuristic and result.scope == "site"
    assert {e.source_url for e in result.evidence} == {HOME}
    distinct = audit(
        page(HOME, doc=labelled("Pricing plans", "Pricing")),
        page(B, doc=labelled("Company founders", "Founders")),
    )
    assert run("F080", distinct)[0].status == "pass"
    assert run("F080", audit(page(HOME)))[0].status == "not_applicable"


def fetch_with(seconds: float, **extra: object) -> dict:
    return {
        "started_at": NOW - timedelta(seconds=seconds),
        "completed_at": NOW,
        **extra,
    }


def test_f101_response_latency() -> None:
    assert status_of("F101", page(HOME, fetch=fetch_with(0.5))) == "pass"
    assert status_of("F101", page(HOME, fetch=fetch_with(3.0))) == "fail"
    assert (
        status_of("F101", page(HOME, fetch=fetch_with(3.0)), latency_budget_seconds=5)
        == "pass"
    )
    assert status_of("F101", page(HOME, fetch=FETCH_TIMEOUT)) == "not_measured"


def test_f102_response_size_and_truncation() -> None:
    body = lambda size, **kw: {
        "body": {
            "ref": "sha256:" + "a" * 64,
            "sha256": "a" * 64,
            "size_bytes": size,
            **kw,
        }
    }  # noqa: E731
    assert status_of("F102", page(HOME, fetch=body(5000))) == "pass"
    assert status_of("F102", page(HOME, fetch=body(5000, truncated=True))) == "fail"
    assert status_of("F102", page(HOME, fetch=body(2_000_000))) == "fail"
    no_body = {"body": None, "body_not_stored_reason": "empty_response"}
    assert (
        status_of("F102", page(HOME, fetch=no_body, no_document=True)) == "not_measured"
    )


def test_f104_and_f105_header_signals() -> None:
    plain = {"headers": {"Content-Type": "text/html"}}
    cached = {
        "headers": {
            "Content-Type": "text/html",
            "Cache-Control": "max-age=60",
            "ETag": '"x"',
        }
    }
    assert status_of("F104", page(HOME, fetch=cached)) == "pass"
    assert status_of("F104", page(HOME, fetch=plain)) == "fail"
    assert status_of("F105", page(HOME, fetch=cached)) == "pass"
    assert status_of("F105", page(HOME, fetch=plain)) == "fail"
    last = {
        "headers": {
            "Content-Type": "text/html",
            "Last-Modified": "Mon, 01 Jan 2026 00:00:00 GMT",
        }
    }
    assert status_of("F105", page(HOME, fetch=last)) == "pass"
    assert status_of("F104", page(HOME, fetch=FETCH_TIMEOUT)) == "not_measured"
    assert (
        statuses("F105", audit(page(HOME, fetch=FETCH_TIMEOUT)))[HOME] == "not_measured"
    )


def test_f110_https_and_hsts() -> None:
    def hdr(value: str | None) -> dict:
        headers = {"Content-Type": "text/html"}
        if value is not None:
            headers["Strict-Transport-Security"] = value
        return {"headers": headers}

    ok = run(
        "F110", audit(page(HOME, fetch=hdr("max-age=31536000; includeSubDomains")))
    )[0]
    assert ok.status == "pass" and ok.observed_value["max_age"] == 31536000
    assert ok.evidence and "Strict-Transport-Security" in ok.evidence[0].snippet
    assert status_of("F110", page(HOME, fetch=hdr('max-age="600"'))) == "pass"
    missing = run("F110", audit(page(HOME, fetch=hdr(None))))[0]
    assert missing.status == "fail" and missing.observed_value["hsts"] is None
    assert status_of("F110", page(HOME, fetch=hdr("max-age=0"))) == "fail"
    assert status_of("F110", page(HOME, fetch=hdr("includeSubDomains"))) == "fail"
    assert status_of("F110", page(HOME, fetch=hdr("max-age=1; max-age=2"))) == "fail"
    assert status_of("F110", page(HOME, fetch=hdr("max-age=abc"))) == "fail"
    http = run("F110", audit(page("http://www.example.com/", fetch=hdr("max-age=60"))))[
        0
    ]
    assert http.status == "fail" and http.observed_value["scheme"] == "http"
    assert status_of("F110", page(HOME, fetch=FETCH_TIMEOUT)) == "not_measured"
    assert ok.severity == "informational"
