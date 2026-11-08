import pytest

from geoptimiser.crawler.robots import RobotsPolicy, parse_rules, pattern_matches
from geoptimiser.schemas import FetchRecord

UA = "GeoptimiserBot"


def policy(text: str, agent: str = UA) -> RobotsPolicy:
    return RobotsPolicy(parse_rules(text, agent))


@pytest.mark.parametrize(
    ("pattern", "target", "expected"),
    [
        ("/", "/anything", True),
        ("/a", "/a", True),
        ("/a", "/ab/c", True),  # prefix match
        ("/a", "/b", False),
        ("/*.php", "/x/y.php", True),
        ("/*.php", "/x/y.phpx", True),
        ("/*.php$", "/x/y.php", True),
        ("/*.php$", "/x/y.phpx", False),
        ("/private$", "/private", True),
        ("/private$", "/private/", False),
        ("/*?id=", "/a?id=5", True),
        ("/*?id=", "/a?x=1&id=5", False),
        ("/a*b*c", "/aXbYc", True),
        ("/a*b*c", "/aXcYb", False),
        ("/a*b*c$", "/aXbYcZ", False),
        ("/*", "/", True),
        ("/a*", "/a", True),
        ("/a$", "/a", True),
        ("/ab*b$", "/ab", False),  # the trailing b may not reuse the earlier one
        ("/ab*b$", "/abb", True),
    ],
)
def test_pattern_matching(pattern: str, target: str, expected: bool) -> None:
    assert pattern_matches(pattern, target) is expected


def test_hostile_patterns_do_not_backtrack_catastrophically() -> None:
    pattern = "/" + "*a" * 200 + "b$"
    assert pattern_matches(pattern, "/" + "a" * 5000) is False


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://x.test/", True),
        ("https://x.test/docs/", True),
        ("https://x.test/docs/a.pdf", False),  # /*.pdf$ (len 7) vs /docs/ allow (len 6)
        ("https://x.test/private/page", False),
        ("https://x.test/private/open/page", True),  # longer Allow beats Disallow
        ("https://x.test/tie", True),  # equal length: Allow wins
        ("https://x.test/a?session=1", False),
        ("https://x.test/a?other=1", True),
    ],
)
def test_longest_match_wins_and_allow_wins_ties(url: str, allowed: bool) -> None:
    robots = policy(
        "User-agent: *\n"
        "Disallow: /private/\n"
        "Allow: /private/open/\n"
        "Disallow: /*.pdf$\n"
        "Allow: /docs/\n"
        "Disallow: /tie\n"
        "Allow: /tie\n"
        "Disallow: /*?session=\n"
    )
    assert robots.allows(url) is allowed


def test_specific_group_overrides_the_wildcard_group() -> None:
    text = "User-agent: *\nDisallow: /\n\nUser-agent: geoptimiserbot\nDisallow: /x/\n"
    robots = policy(text)
    assert robots.allows("https://x.test/page")
    assert not robots.allows("https://x.test/x/page")


def test_specific_group_without_rules_allows_everything() -> None:
    robots = policy(
        "User-agent: *\nDisallow: /\n\nUser-agent: GeoptimiserBot\nDisallow:\n"
    )
    assert robots.allows("https://x.test/anything")


def test_multiple_user_agent_lines_share_one_group_and_groups_merge() -> None:
    text = (
        "User-agent: otherbot\nUser-agent: GeoptimiserBot\nDisallow: /a\n"
        "User-agent: GeoptimiserBot\nDisallow: /b\n"
    )
    robots = policy(text)
    assert not robots.allows("https://x.test/a") and not robots.allows(
        "https://x.test/b"
    )
    assert robots.allows("https://x.test/c")


def test_comments_case_crlf_and_unknown_fields_are_tolerated() -> None:
    text = (
        "# header\r\nUSER-AGENT: *  # everyone\r\nDISALLOW: /secret # hidden\r\n"
        "Crawl-delay: 10\r\nSitemap: https://x.test/s.xml\r\nnot a field\r\n"
    )
    robots = policy(text)
    assert not robots.allows("https://x.test/secret")
    assert robots.allows("https://x.test/open")


def test_rules_before_any_user_agent_are_ignored() -> None:
    assert policy("Disallow: /\nUser-agent: *\nDisallow: /x\n").allows(
        "https://x.test/"
    )


def test_percent_escape_case_is_normalized() -> None:
    robots = policy("User-agent: *\nDisallow: /a%2fb\n")
    assert not robots.allows("https://x.test/a%2Fb")


def test_empty_or_missing_rules_allow_everything() -> None:
    assert policy("").allows("https://x.test/x")
    assert policy("User-agent: other\nDisallow: /\n").allows("https://x.test/x")


def fetch_record(outcome: str, status: int | None, **extra: object) -> FetchRecord:
    fields: dict[str, object] = {
        "audit_id": "aud_t",
        "fetch_id": "f1",
        "requested_url": "https://x.test/robots.txt",
        "outcome": outcome,
        "started_at": "2026-01-01T00:00:00Z",
        "completed_at": "2026-01-01T00:00:01Z",
    }
    if outcome == "transport_error":
        fields |= {"error_type": "timeout", "error_message": "t"}
    else:
        fields |= {"status_code": status, "final_url": "https://x.test/robots.txt"}
    if outcome == "success":
        fields["body_not_stored_reason"] = "empty_response"
    if outcome == "redirect_not_followed":
        fields["redirect_refusal_reason"] = "cross_domain"
    return FetchRecord.model_validate(fields | extra)


@pytest.mark.parametrize(
    ("outcome", "status", "allowed"),
    [
        ("success", 200, True),  # empty file
        ("http_error", 404, True),
        ("http_error", 403, True),
        ("http_error", 500, False),
        ("http_error", 503, False),
        ("transport_error", None, False),
        ("redirect_not_followed", 302, False),
    ],
)
def test_unreadable_robots_follows_rfc_9309(
    outcome: str, status: int | None, allowed: bool
) -> None:
    record = fetch_record(outcome, status)
    robots = RobotsPolicy.from_fetch(record, None, "GeoptimiserBot/0.1")
    assert robots.allows("https://x.test/page") is allowed


def test_from_fetch_parses_a_body() -> None:
    record = fetch_record("success", 200)
    body = b"User-agent: *\nDisallow: /*.zip$\n"
    robots = RobotsPolicy.from_fetch(record, body, "GeoptimiserBot/0.1")
    assert not robots.allows("https://x.test/a.zip") and robots.allows(
        "https://x.test/a"
    )
