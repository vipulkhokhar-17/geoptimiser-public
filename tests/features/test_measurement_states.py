"""Pass, fail, not applicable, not measured and fetch errors stay distinct (A2, B3)."""

from geoptimiser.features.checks import crawl as _crawl  # noqa: F401
from tests.features.builders import (
    FETCH_404,
    FETCH_REFUSED,
    FETCH_TIMEOUT,
    audit,
    page,
    robots_file,
    run,
    status_of,
)

HOME = "https://www.example.com/"
A = "https://www.example.com/a"


def f12(target_fetch: dict | None, **target_doc: object) -> str:
    pages = [page(HOME, doc={"canonical_url": A})]
    if target_fetch is not None:
        pages.append(page(A, fetch=target_fetch, doc=target_doc))
    return run("F012", audit(*pages))[0].status


def test_canonical_target_states() -> None:
    assert f12(None) == "not_measured"  # never crawled: unknown, not healthy
    assert f12({}) == "pass"
    assert f12(FETCH_404) == "fail"
    assert f12({}, meta_robots="noindex") == "fail"
    assert f12(FETCH_TIMEOUT) == "not_measured"  # a fetch error is not a site defect
    assert f12(FETCH_REFUSED) == "not_measured"


def test_canonical_target_with_server_or_access_errors_is_not_a_missing_page() -> None:
    for status in (401, 403, 429, 500, 503):
        fetch = FETCH_404 | {"status_code": status}
        assert f12(fetch) == "not_measured", status
    for status in (404, 410):
        assert f12(FETCH_404 | {"status_code": status}) == "fail", status


def test_malformed_canonical_is_a_failure_whatever_the_target() -> None:
    p = page(HOME, doc={"canonical_url": "javascript:void(0)"})
    assert run("F012", audit(p))[0].status == "fail"


def test_robots_body_that_cannot_be_read_is_not_allow_all() -> None:
    robots = robots_file("User-agent: *\nDisallow: /\n")
    unreadable = type(robots)(robots.origin, robots.record, None)  # body lost
    assert run("F004", audit(page(HOME), robots=(unreadable,)))[0].status == (
        "not_measured"
    )


def test_empty_robots_file_allows_everything() -> None:
    robots = robots_file("")
    empty = type(robots)(
        robots.origin,
        robots.record.model_copy(
            update={"body": None, "body_not_stored_reason": "empty_response"}
        ),
        None,
    )
    assert run("F004", audit(page(HOME), robots=(empty,)))[0].status == "pass"


def test_truncated_robots_without_a_block_is_not_a_clean_pass() -> None:
    robots = robots_file("User-agent: *\nAllow: /\n")
    body = robots.record.body.model_copy(update={"truncated": True})  # type: ignore[union-attr]
    cut = type(robots)(
        robots.origin, robots.record.model_copy(update={"body": body}), robots.text
    )
    assert run("F004", audit(page(HOME), robots=(cut,)))[0].status == "not_measured"
    blocked = type(robots)(
        robots.origin,
        robots.record.model_copy(update={"body": body}),
        "User-agent: GPTBot\nDisallow: /\n",
    )
    assert run("F004", audit(page(HOME), robots=(blocked,)))[0].status == "warning"


def test_redirect_checks_apply_only_to_redirected_pages() -> None:
    assert status_of("F015", page(HOME)) == "not_applicable"
    assert status_of("F016", page(HOME)) == "not_applicable"


def test_url_parameter_check_sees_linked_urls_the_crawler_never_fetches() -> None:
    links = ["https://www.example.com/list?a=1&b=2&c=3&d=4&e=5"]
    fail = run("F018", audit(page(HOME, doc={"links": links})))[0]
    assert (
        fail.status == "fail"
        and fail.observed_value["max_parameters_in_linked_urls"] == 5
    )
    ok = run(
        "F018", audit(page(HOME, doc={"links": ["https://www.example.com/p?a=1"]}))
    )[0]
    assert ok.status == "pass"
    assert (
        status_of("F018", page("https://www.example.com/x?a=1&b=2&c=3&d=4")) == "fail"
    )


def test_owner_policy_checks_report_warnings_with_a_severity_that_fits() -> None:
    entry = page(HOME, doc={"meta_robots": "noindex"})
    other = page(A, doc={"meta_robots": "noindex"})
    results = {r.subject_url: r for r in run("F005", audit(entry, other))}
    assert results[HOME].status == results[A].status == "warning"
    assert results[HOME].severity == "medium" and results[A].severity == "low"
    assert "Confirm intent" in (results[A].explanation or "")


def test_unreadable_extraction_failure_says_why() -> None:
    from geoptimiser.features.inputs import PageContext
    from geoptimiser.schemas import ExtractionFailure
    from tests.features.builders import make_fetch

    fetch = make_fetch(HOME)
    failure = ExtractionFailure(
        audit_id=fetch.audit_id,
        fetch_id=fetch.fetch_id,
        extraction_version="html-extractor:3",
        error_type="unsupported_content_type",
        error_message="text/plain is not HTML",
    )
    inputs = audit(PageContext(fetch, None, failure))
    r = run("F021", inputs)[0]
    assert r.status == "not_measured"
    assert "unsupported_content_type" in (r.explanation or "")
    assert "text/plain is not HTML" in (r.explanation or "")


def test_blocked_or_failing_link_targets_are_not_counted_as_broken() -> None:
    home = page(HOME, doc={"links": [A, "https://www.example.com/b"]})
    refused = page(A, fetch=FETCH_404 | {"status_code": 403})
    gone = page("https://www.example.com/b", fetch=FETCH_404)
    only_refused = run("F017", audit(home, refused))[0]
    assert only_refused.status == "not_measured"  # nothing verifiable was crawled
    both = run("F017", audit(home, refused, gone))[0]
    assert both.status == "fail"
    assert both.observed_value == {
        "checked": 1,
        "broken": ["https://www.example.com/b"],
    }
