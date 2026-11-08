import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from geoptimiser.crawler import (
    ArtifactWriter,
    CrawlConfig,
    Crawler,
    CrawlResult,
    FetchResult,
    LocalBodyStore,
    SafeFetcher,
    StorageError,
    read_fetches,
)
from geoptimiser.crawler.__main__ import main
from geoptimiser.crawler.urls import host_in_scope
from geoptimiser.schemas import AuditRequest, FetchRecord
from tests.crawler.conftest import MockSite

Make = Callable[..., SafeFetcher]
MakeConfig = Callable[..., CrawlConfig]


def audit_request() -> AuditRequest:
    return AuditRequest(
        audit_id="aud_test",
        target_domain="site.test",
        brand_name="Site",
        business_context="test",
        target_audience="testers",
        authorization_confirmed=True,
    )


def run(
    site: MockSite, make_fetcher: Make, config: CrawlConfig, **kwargs: object
) -> CrawlResult:
    fetcher = make_fetcher(config, host_allowed=lambda h: host_in_scope(h, "site.test"))
    return Crawler(
        audit_request(), config, fetcher, seed_url=site.url(), **kwargs
    ).run()  # type: ignore[arg-type]


def page_paths(result: CrawlResult) -> list[str]:
    return [
        str(f.requested_url.path)
        for f in result.fetches
        if f.requested_url.path != "/robots.txt"
    ]


@pytest.fixture
def linked_site(site: MockSite) -> MockSite:
    site.add(
        "/robots.txt", "User-agent: *\nDisallow: /private/\n", content_type="text/plain"
    )
    site.html(
        "/",
        "/a",
        "/b#section",
        "/a",  # duplicate
        "https://elsewhere.test/x",  # off-site
        "mailto:x@y.z",
        "/file.pdf",
        "/search?q=1",
        "/private/secret",
    )
    site.html("/a", "/c", "/")
    site.html("/b")
    site.html("/c", "/d")
    site.html("/d")
    return site


def test_breadth_first_discovery_within_scope(
    linked_site: MockSite, make_fetcher: Make, make_config: MakeConfig
) -> None:
    result = run(linked_site, make_fetcher, make_config(max_depth=3))

    assert page_paths(result) == ["/", "/a", "/b", "/c", "/d"]
    assert result.stop_reason == "completed"
    assert all(f.audit_id == "aud_test" for f in result.fetches)
    assert not {"/file.pdf", "/search"} & set(linked_site.paths_requested())


def test_depth_limit(
    linked_site: MockSite, make_fetcher: Make, make_config: MakeConfig
) -> None:
    assert page_paths(run(linked_site, make_fetcher, make_config(max_depth=0))) == ["/"]
    assert page_paths(run(linked_site, make_fetcher, make_config(max_depth=1))) == [
        "/",
        "/a",
        "/b",
    ]


def test_page_limit_counts_pages_not_robots(
    linked_site: MockSite, make_fetcher: Make, make_config: MakeConfig
) -> None:
    result = run(linked_site, make_fetcher, make_config(max_pages=2, max_depth=3))

    assert page_paths(result) == ["/", "/a"]
    assert result.stop_reason == "max_pages"
    assert any(f.requested_url.path == "/robots.txt" for f in result.fetches)


def test_robots_disallowed_urls_are_skipped_not_fetched(
    linked_site: MockSite, make_fetcher: Make, make_config: MakeConfig
) -> None:
    result = run(linked_site, make_fetcher, make_config())

    assert "/private/secret" not in linked_site.paths_requested()
    assert [(s.url.endswith("/private/secret"), s.reason) for s in result.skipped] == [
        (True, "robots_disallowed")
    ]
    assert "/private/secret" not in page_paths(result)  # skipped != failed fetch


def test_robots_can_be_disabled(
    linked_site: MockSite, make_fetcher: Make, make_config: MakeConfig
) -> None:
    run(linked_site, make_fetcher, make_config(respect_robots=False))
    assert "/robots.txt" not in linked_site.paths_requested()
    assert "/private/secret" in linked_site.paths_requested()


def test_missing_robots_allows_everything(
    site: MockSite, make_fetcher: Make, make_config: MakeConfig
) -> None:
    site.html("/", "/a")
    site.html("/a")

    result = run(site, make_fetcher, make_config())
    assert page_paths(result) == ["/", "/a"] and not result.skipped
    robots = result.fetches[0]
    assert robots.status_code == 404


def test_unreadable_robots_disallows_the_origin(
    site: MockSite, make_fetcher: Make, make_config: MakeConfig
) -> None:
    site.add("/robots.txt", "oops", status=503)
    site.html("/")

    result = run(site, make_fetcher, make_config())
    assert page_paths(result) == [] and len(result.skipped) == 1
    assert site.paths_requested() == ["/robots.txt"]


def test_audit_byte_budget_stops_the_crawl_and_flags_truncation(
    site: MockSite, make_fetcher: Make, make_config: MakeConfig
) -> None:
    for path in ("/", "/a", "/b"):
        site.add(path, f'<a href="/a"></a><a href="/b"></a>{"x" * 600}')

    result = run(
        site, make_fetcher, make_config(max_audit_bytes=1000, respect_robots=False)
    )
    sizes = [f.body.size_bytes for f in result.fetches if f.body]
    assert sum(sizes) <= 1000
    assert result.fetches[-1].body is not None and result.fetches[-1].body.truncated
    assert result.stop_reason == "audit_byte_budget"
    assert len(result.fetches) == 2


def test_audit_time_limit(
    linked_site: MockSite, make_fetcher: Make, make_config: MakeConfig
) -> None:
    now = [0.0]

    def clock() -> float:
        now[0] += 100  # every reading advances time
        return now[0]

    result = run(
        linked_site,
        make_fetcher,
        make_config(max_audit_seconds=250, max_depth=3),
        clock=clock,
    )
    assert result.stop_reason == "audit_timeout"
    assert len(page_paths(result)) < 5


def test_requests_are_rate_limited(
    linked_site: MockSite, make_fetcher: Make, make_config: MakeConfig
) -> None:
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    result = run(
        linked_site,
        make_fetcher,
        make_config(min_request_interval_seconds=2.0, max_depth=1),
        clock=lambda: now[0],
        sleep=sleep,
    )
    assert len(sleeps) == len(result.fetches) - 1
    assert all(abs(s - 2.0) < 1e-9 for s in sleeps)


def test_redirects_to_other_hosts_are_not_followed_and_not_crawled(
    site: MockSite, make_fetcher: Make, make_config: MakeConfig
) -> None:
    site.html("/", "/moved")
    site.add(
        "/moved", status=301, headers={"Location": f"http://evil.test:{site.port}/x"}
    )
    site.html("/x")

    result = run(site, make_fetcher, make_config(respect_robots=False))
    moved = next(f for f in result.fetches if f.requested_url.path == "/moved")
    assert moved.redirect_refusal_reason == "cross_domain"
    assert "/x" not in site.paths_requested()


def test_redirect_destination_is_not_fetched_again_as_a_link(
    site: MockSite, make_fetcher: Make, make_config: MakeConfig
) -> None:
    site.html("/", "/old", "/new")
    site.add("/old", status=301, headers={"Location": "/new"})
    site.html("/new")

    result = run(site, make_fetcher, make_config(respect_robots=False))

    assert site.paths_requested().count("/new") == 1  # via the redirect only
    assert [f.outcome for f in result.fetches] == ["success", "success"]
    assert str(result.fetches[1].final_url).endswith("/new")


def test_link_to_an_already_fetched_redirect_destination_is_not_queued(
    site: MockSite, make_fetcher: Make, make_config: MakeConfig
) -> None:
    site.html("/", "/old")
    site.add("/old", status=301, headers={"Location": "/new"})
    site.html("/new", "/old", "/new")  # links back to both

    run(site, make_fetcher, make_config(respect_robots=False, max_depth=3))
    assert site.paths_requested().count("/new") == 1
    assert site.paths_requested().count("/old") == 1


def test_failed_pages_do_not_stop_the_crawl(
    site: MockSite, make_fetcher: Make, make_config: MakeConfig
) -> None:
    site.html("/", "/missing", "/ok")
    site.html("/ok")

    result = run(site, make_fetcher, make_config(respect_robots=False))
    outcomes = {f.requested_url.path: f.outcome for f in result.fetches}
    assert outcomes == {"/": "success", "/missing": "http_error", "/ok": "success"}


def test_seed_must_be_in_scope(
    site: MockSite, make_fetcher: Make, make_config: MakeConfig
) -> None:
    config = make_config()
    with pytest.raises(ValueError, match="inside the target domain"):
        Crawler(
            audit_request(), config, make_fetcher(config), seed_url="http://evil.test/"
        )


class _RecordingFetcher:
    """Stands in for SafeFetcher: records the URLs asked for, never connects."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def fetch(self, url: str, **kwargs: object) -> FetchResult:
        self.urls.append(url)
        record = FetchRecord(
            audit_id="aud_test",
            fetch_id=f"fetch_{len(self.urls)}",
            requested_url=url,
            outcome="transport_error",
            error_type="dns",
            error_message="stub",
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
        return FetchResult(record, None)


def test_default_seed_is_the_https_root_of_the_target(
    make_config: MakeConfig,
) -> None:
    config = make_config(respect_robots=False)
    fetcher = _RecordingFetcher()

    result = Crawler(audit_request(), config, fetcher).run()  # type: ignore[arg-type]

    assert fetcher.urls == ["https://site.test/"]
    assert result.stop_reason == "completed"


def test_artifacts_round_trip_and_keep_bodies_out_of_records(
    linked_site: MockSite,
    make_fetcher: Make,
    make_config: MakeConfig,
    store: LocalBodyStore,
    tmp_path: Path,
) -> None:
    out = tmp_path / "out"
    with ArtifactWriter(out) as sink:
        result = run(linked_site, make_fetcher, make_config(), sink=sink)

    lines = (out / "fetches.jsonl").read_text().splitlines()
    records = [FetchRecord.model_validate_json(line) for line in lines]
    assert records == list(result.fetches)
    assert "<html>" not in "\n".join(lines)
    for record in records:
        if record.body:
            data = store.get(record.body.ref)
            assert len(data) == record.body.size_bytes

    skipped = (out / "skipped_urls.jsonl").read_text().splitlines()
    assert len(skipped) == 1 and json.loads(skipped[0])["reason"] == "robots_disallowed"
    summary = json.loads((out / "crawl_summary.json").read_text())
    assert summary["audit_id"] == "aud_test"
    assert summary["stop_reason"] == "completed"
    assert summary["fetch_count"] == len(records)
    assert summary["config"]["max_pages"] == 25  # limits are recorded for provenance


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_pages": 0},
        {"max_response_bytes": 0},
        {"request_timeout_seconds": 0},
        {"max_fetch_seconds": -1},
        {"max_pages": 10_000},
        {"unknown": 1},
    ],
)
def test_config_rejects_unbounded_or_invalid_limits(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        CrawlConfig(**overrides)  # type: ignore[arg-type]


def test_cli_requires_authorization_attestation(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--domain", "example.com", "--out", str(tmp_path)])


# --- robots on redirect destinations and wildcard rules --------------------------


def test_redirect_into_a_robots_disallowed_path_is_not_fetched(
    linked_site: MockSite, make_fetcher: Make, make_config: MakeConfig
) -> None:
    linked_site.html("/", "/go")
    linked_site.add("/go", status=301, headers={"Location": "/private/x"})
    linked_site.html("/private/x")

    result = run(linked_site, make_fetcher, make_config())

    go = next(f for f in result.fetches if f.requested_url.path == "/go")
    assert go.outcome == "redirect_not_followed"
    assert go.redirect_refusal_reason == "robots_disallowed"
    assert go.status_code == 301
    assert "/private/x" not in linked_site.paths_requested()


def test_redirect_to_an_allowed_path_is_followed_with_robots_enabled(
    linked_site: MockSite, make_fetcher: Make, make_config: MakeConfig
) -> None:
    linked_site.html("/", "/go")
    linked_site.add("/go", status=301, headers={"Location": "/ok"})
    linked_site.html("/ok")

    result = run(linked_site, make_fetcher, make_config())
    assert any(str(f.final_url).endswith("/ok") for f in result.fetches)


def test_wildcard_and_end_anchor_rules_are_applied(
    site: MockSite, make_fetcher: Make, make_config: MakeConfig
) -> None:
    site.add(
        "/robots.txt",
        "User-agent: *\nDisallow: /*/draft$\nDisallow: /tmp*\nAllow: /tmp/ok\n",
        content_type="text/plain",
    )
    site.html("/", "/docs/draft", "/docs/draft2", "/tmpfile", "/tmp/ok")
    for path in ("/docs/draft", "/docs/draft2", "/tmpfile", "/tmp/ok"):
        site.html(path)

    result = run(site, make_fetcher, make_config())

    requested = set(site.paths_requested())
    assert {"/docs/draft2", "/tmp/ok"} <= requested
    assert not {"/docs/draft", "/tmpfile"} & requested
    assert {s.url.rsplit(":", 1)[-1].split("/", 1)[1] for s in result.skipped} == {
        "docs/draft",
        "tmpfile",
    }


# --- audit byte budget never exceeded ------------------------------------------------


def total_stored(result: CrawlResult) -> int:
    return sum(f.body.size_bytes for f in result.fetches if f.body)


def test_robots_cannot_push_the_audit_over_budget(
    site: MockSite, make_fetcher: Make, make_config: MakeConfig
) -> None:
    site.add(
        "/robots.txt",
        "User-agent: *\nAllow: /\n" + "#" * 600,
        content_type="text/plain",
    )
    site.html("/", "/a")
    site.html("/a")

    result = run(site, make_fetcher, make_config(max_audit_bytes=500))

    assert total_stored(result) <= 500
    assert result.stop_reason == "audit_byte_budget"
    assert [(s.reason, s.url.endswith("/")) for s in result.skipped] == [
        ("byte_budget_exhausted", True)
    ]
    assert site.paths_requested() == ["/robots.txt"]  # the page was never requested


@pytest.mark.parametrize("budget", [1, 40, 123, 500, 5000])
def test_total_stored_bytes_never_exceed_the_budget(
    site: MockSite, make_fetcher: Make, make_config: MakeConfig, budget: int
) -> None:
    for path in ("/", "/a", "/b"):
        site.add(path, f'<a href="/a"></a><a href="/b"></a>{"x" * 300}')

    result = run(
        site, make_fetcher, make_config(max_audit_bytes=budget, respect_robots=False)
    )
    assert total_stored(result) <= budget


# --- durable artifacts ---------------------------------------------------------------


def test_records_are_written_while_the_crawl_runs(
    linked_site: MockSite, make_fetcher: Make, make_config: MakeConfig, tmp_path: Path
) -> None:
    seen: list[int] = []

    class Spy(ArtifactWriter):
        def write_fetch(self, record: object) -> None:
            super().write_fetch(record)  # type: ignore[arg-type]
            seen.append(
                len((tmp_path / "a" / "fetches.jsonl").read_text().splitlines())
            )

    with Spy(tmp_path / "a") as sink:
        result = run(linked_site, make_fetcher, make_config(), sink=sink)

    assert seen == list(range(1, len(result.fetches) + 1))


def test_storage_failure_aborts_but_keeps_earlier_records(
    site: MockSite,
    make_fetcher: Make,
    make_config: MakeConfig,
    store: LocalBodyStore,
    tmp_path: Path,
) -> None:
    site.html("/", "/a", "/b")
    site.html("/a")
    site.html("/b")
    puts = []
    real_put = store.put

    def failing_put(data: bytes, *, truncated: bool = False):  # type: ignore[no-untyped-def]
        puts.append(1)
        if len(puts) == 2:
            raise OSError(28, "No space left on device")
        return real_put(data, truncated=truncated)

    store.put = failing_put  # type: ignore[method-assign]
    out = tmp_path / "out"
    with pytest.raises(StorageError), ArtifactWriter(out) as sink:
        run(site, make_fetcher, make_config(respect_robots=False), sink=sink)

    records = read_fetches(out / "fetches.jsonl")
    assert [r.requested_url.path for r in records] == ["/"]
    summary = json.loads((out / "crawl_summary.json").read_text())
    assert summary["stop_reason"] == "aborted" and summary["error"] == "StorageError"
    assert summary["fetch_count"] == 1


def test_interrupt_keeps_records_and_writes_an_aborted_summary(
    linked_site: MockSite, make_fetcher: Make, make_config: MakeConfig, tmp_path: Path
) -> None:
    config = make_config(respect_robots=False)
    fetcher = make_fetcher(config, host_allowed=lambda h: True)
    real_fetch = fetcher.fetch
    calls = []

    def interrupting(url: str, **kwargs: object) -> FetchResult:
        calls.append(url)
        if len(calls) == 3:
            raise KeyboardInterrupt
        return real_fetch(url, **kwargs)  # type: ignore[arg-type]

    fetcher.fetch = interrupting  # type: ignore[method-assign]
    out = tmp_path / "out"
    with pytest.raises(KeyboardInterrupt), ArtifactWriter(out) as sink:
        Crawler(
            audit_request(), config, fetcher, seed_url=linked_site.url(), sink=sink
        ).run()

    assert len(read_fetches(out / "fetches.jsonl")) == 2
    summary = json.loads((out / "crawl_summary.json").read_text())
    assert summary["stop_reason"] == "aborted"
    assert summary["error"] == "KeyboardInterrupt"


def test_skipped_urls_are_written_incrementally(
    linked_site: MockSite, make_fetcher: Make, make_config: MakeConfig, tmp_path: Path
) -> None:
    with ArtifactWriter(tmp_path / "o") as sink:
        run(linked_site, make_fetcher, make_config(), sink=sink)
    lines = (tmp_path / "o" / "skipped_urls.jsonl").read_text().splitlines()
    assert [json.loads(line)["reason"] for line in lines] == ["robots_disallowed"]
