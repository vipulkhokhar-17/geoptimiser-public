import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from geoptimiser.crawler import (
    ArtifactWriter,
    CrawlConfig,
    Crawler,
    LocalBodyStore,
    SafeFetcher,
    read_fetches,
)
from geoptimiser.crawler.urls import host_in_scope
from geoptimiser.extraction import (
    EXTRACTION_VERSION,
    ExtractionConfig,
    ExtractionWriter,
    extract_all,
    extract_fetch,
    read_documents,
    skip_reason,
)
from geoptimiser.extraction.__main__ import main
from geoptimiser.schemas import (
    AuditRequest,
    ExtractionFailure,
    FetchRecord,
    PageDocument,
    check_extraction_source,
)
from tests.crawler.conftest import MockSite

NOW = datetime(2026, 3, 1, 9, 30, tzinfo=UTC)
Read = Callable[[str], str]


def clock() -> datetime:
    return NOW


def make_fetch(
    store: LocalBodyStore,
    html: str | bytes,
    *,
    fetch_id: str = "fetch_001",
    content_type: str | None = "text/html; charset=utf-8",
    url: str = "https://www.example.com/pricing",
    truncated: bool = False,
    **overrides: Any,
) -> FetchRecord:
    data = html.encode() if isinstance(html, str) else html
    fields: dict[str, Any] = {
        "audit_id": "aud_test",
        "fetch_id": fetch_id,
        "requested_url": url,
        "outcome": "success",
        "status_code": 200,
        "final_url": url,
        "headers": {"Content-Type": content_type} if content_type else {},
        "body": store.put(data, truncated=truncated).model_dump(),
        "started_at": NOW,
        "completed_at": NOW,
    }
    return FetchRecord.model_validate(fields | overrides)


def doc(result: PageDocument | ExtractionFailure) -> PageDocument:
    assert isinstance(result, PageDocument), result
    return result


def failure(result: PageDocument | ExtractionFailure) -> ExtractionFailure:
    assert isinstance(result, ExtractionFailure), result
    return result


# --- a successful extraction carries provenance -------------------------------


def test_document_fields_and_provenance(
    store: LocalBodyStore, fixture_html: Read
) -> None:
    fetch = make_fetch(store, fixture_html("full_page"))

    document = doc(extract_fetch(fetch, store, clock=clock))

    assert (document.audit_id, document.fetch_id) == ("aud_test", "fetch_001")
    assert str(document.url) == "https://www.example.com/pricing"
    assert document.extraction_version == EXTRACTION_VERSION == "html-extractor:3"
    assert document.document_id == "doc:fetch_001:html-extractor:3"
    assert document.extracted_at == NOW
    assert document.encoding == "utf-8" and not document.source_truncated
    assert document.title == "Acme & Co — Pricing"
    assert [(h.level, h.text) for h in document.headings][0] == (1, "Pricing plans")
    assert document.structured_data_errors == 1
    assert document.truncated_fields == ()
    assert document.schema_version == 1
    check_extraction_source(fetch, document)  # the cross-record rule holds
    assert PageDocument.model_validate_json(document.model_dump_json()) == document


def test_document_url_is_the_final_url_after_redirects(store: LocalBodyStore) -> None:
    fetch = make_fetch(
        store,
        "<title>New</title>",
        url="https://www.example.com/new",
        requested_url="https://www.example.com/old",
        redirects=[
            {
                "url": "https://www.example.com/old",
                "status_code": 301,
                "location": "/new",
            }
        ],
    )
    document = doc(extract_fetch(fetch, store, clock=clock))
    assert str(document.url) == "https://www.example.com/new"
    assert str(fetch.requested_url) == "https://www.example.com/old"  # via fetch_id


def test_truncated_source_is_flagged(store: LocalBodyStore) -> None:
    fetch = make_fetch(store, "<title>Cut</title><p>text that was cut", truncated=True)
    document = doc(extract_fetch(fetch, store, clock=clock))
    assert document.source_truncated is True


def test_extraction_limits_are_reported_on_the_document(store: LocalBodyStore) -> None:
    links = "".join(f'<a href="/{i}">x</a>' for i in range(20))
    fetch = make_fetch(store, links)
    document = doc(extract_fetch(fetch, store, ExtractionConfig(max_links=5)))
    assert len(document.links) == 5 and document.truncated_fields == ("links",)


def test_non_utf8_page_is_decoded_with_its_declared_charset(
    store: LocalBodyStore,
) -> None:
    html = "<title>Café</title><p>naïve</p>".encode("latin-1")
    fetch = make_fetch(store, html, content_type="text/html; charset=ISO-8859-1")
    document = doc(extract_fetch(fetch, store))
    assert document.title == "Café" and document.text == "naïve"
    assert document.encoding == "iso8859-1"


@pytest.mark.parametrize("name", ["empty", "blank"])
def test_empty_pages_are_documents_not_failures(
    store: LocalBodyStore, fixture_html: Read, name: str
) -> None:
    document = doc(extract_fetch(make_fetch(store, fixture_html(name)), store))
    assert document.text == "" and document.title is None
    assert document.headings == () and document.links == ()


def test_malformed_page_still_yields_a_document(
    store: LocalBodyStore, fixture_html: Read
) -> None:
    document = doc(extract_fetch(make_fetch(store, fixture_html("malformed")), store))
    assert document.title == "Messy & page"


# --- explicit failures --------------------------------------------------------


@pytest.mark.parametrize("content_type", ["application/pdf", "image/png", None])
def test_unsupported_content_type_is_a_failure(
    store: LocalBodyStore, content_type: str | None
) -> None:
    fetch = make_fetch(store, b"%PDF-1.7", content_type=content_type)
    result = failure(extract_fetch(fetch, store, clock=clock))
    assert result.error_type == "unsupported_content_type"
    assert result.extraction_version == EXTRACTION_VERSION
    assert result.occurred_at == NOW
    check_extraction_source(fetch, result)


def test_xhtml_is_supported(store: LocalBodyStore) -> None:
    fetch = make_fetch(store, "<title>X</title>", content_type="application/xhtml+xml")
    assert doc(extract_fetch(fetch, store)).title == "X"


def test_undecodable_body_is_a_decode_error(store: LocalBodyStore) -> None:
    fetch = make_fetch(store, b"\xff\xfe\xfd" * 200)
    assert failure(extract_fetch(fetch, store)).error_type == "decode_error"


def test_missing_stored_body_is_a_failure(
    store: LocalBodyStore, tmp_path: Path
) -> None:
    fetch = make_fetch(store, "<p>x</p>")
    empty = LocalBodyStore(tmp_path / "elsewhere")
    result = failure(extract_fetch(fetch, empty))
    assert result.error_type == "other" and "not found" in result.error_message


def test_tampered_body_fails_the_integrity_check(store: LocalBodyStore) -> None:
    fetch = make_fetch(store, "<p>original</p>")
    assert fetch.body is not None
    path = store.root / fetch.body.sha256[:2] / fetch.body.sha256
    path.write_bytes(b"<p>tampered</p>")

    result = failure(extract_fetch(fetch, store))
    assert result.error_type == "other"
    assert (
        "does not match" in result.error_message or "integrity" in result.error_message
    )


def test_record_with_a_wrong_hash_fails_the_integrity_check(
    store: LocalBodyStore,
) -> None:
    good = make_fetch(store, "<p>content</p>")
    assert good.body is not None
    forged = good.model_dump() | {
        "body": good.body.model_dump() | {"sha256": hashlib.sha256(b"x").hexdigest()}
    }
    result = failure(extract_fetch(FetchRecord.model_validate(forged), store))
    assert "integrity" in result.error_message


def test_record_with_a_wrong_size_fails_the_integrity_check(
    store: LocalBodyStore,
) -> None:
    good = make_fetch(store, "<p>content</p>")
    assert good.body is not None
    forged = good.model_dump() | {"body": good.body.model_dump() | {"size_bytes": 3}}
    result = failure(extract_fetch(FetchRecord.model_validate(forged), store))
    assert "integrity" in result.error_message


def test_oversized_body_is_refused_before_reading(store: LocalBodyStore) -> None:
    fetch = make_fetch(store, "<p>" + "x" * 500 + "</p>")
    result = failure(extract_fetch(fetch, store, ExtractionConfig(max_input_bytes=100)))
    assert result.error_type == "other" and "exceeds" in result.error_message


def test_parse_time_limit_is_a_parse_error(store: LocalBodyStore) -> None:
    fetch = make_fetch(store, "<p>x</p>" * 100)
    result = failure(extract_fetch(fetch, store, ExtractionConfig(max_seconds=1e-9)))
    assert result.error_type == "parse_error" and "time limit" in result.error_message


def test_parser_crash_is_contained(
    store: LocalBodyStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("secret page content must not leak")

    monkeypatch.setattr("geoptimiser.extraction.pipeline.parse_html", boom)
    result = failure(extract_fetch(make_fetch(store, "<p>x</p>"), store))
    assert result.error_type == "parse_error"
    assert "AssertionError" in result.error_message
    assert "secret" not in result.error_message  # exception text is not copied


def test_unexpected_error_is_contained(store: LocalBodyStore) -> None:
    class BrokenStore:
        def get(self, ref: str) -> bytes:
            raise KeyError("boom")

    fetch = make_fetch(store, "<p>x</p>")
    result = failure(extract_fetch(fetch, BrokenStore()))  # type: ignore[arg-type]
    assert result.error_type == "other" and "KeyError" in result.error_message


def test_keyboard_interrupt_is_not_swallowed(store: LocalBodyStore) -> None:
    class InterruptedStore:
        def get(self, ref: str) -> bytes:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        extract_fetch(make_fetch(store, "<p>x</p>"), InterruptedStore())  # type: ignore[arg-type]


# --- what is not extracted at all ---------------------------------------------


def non_page_fetches(store: LocalBodyStore) -> dict[str, FetchRecord]:
    base = make_fetch(store, "<p>x</p>")
    return {
        "not_successful_fetch": FetchRecord.model_validate(
            {
                "audit_id": "aud_test",
                "fetch_id": "fetch_err",
                "requested_url": "https://www.example.com/x",
                "outcome": "transport_error",
                "error_type": "timeout",
                "error_message": "t",
                "started_at": NOW,
                "completed_at": NOW,
            }
        ),
        "no_stored_body": make_fetch(
            store,
            b"",
            fetch_id="fetch_empty",
            body=None,
            body_not_stored_reason="empty_response",
        ),
        "robots_txt": make_fetch(
            store,
            "User-agent: *\n",
            fetch_id="fetch_robots",
            content_type="text/plain",
            url="https://www.example.com/robots.txt",
        ),
        "http_error": FetchRecord.model_validate(
            base.model_dump()
            | {
                "fetch_id": "fetch_404",
                "outcome": "http_error",
                "status_code": 404,
                "body": None,
                "body_not_stored_reason": "non_success_status",
            }
        ),
    }


def test_skip_reasons(store: LocalBodyStore) -> None:
    fetches = non_page_fetches(store)
    assert skip_reason(fetches["not_successful_fetch"]) == "not_successful_fetch"
    assert skip_reason(fetches["http_error"]) == "not_successful_fetch"
    assert skip_reason(fetches["no_stored_body"]) == "no_stored_body"
    assert skip_reason(fetches["robots_txt"]) == "robots_txt"
    assert skip_reason(make_fetch(store, "<p>x</p>")) is None


def test_extract_fetch_refuses_non_extractable_fetches(store: LocalBodyStore) -> None:
    for fetch in non_page_fetches(store).values():
        with pytest.raises(ValueError, match="not extractable"):
            extract_fetch(fetch, store)


def test_extract_all_sorts_pages_failures_and_skips(
    store: LocalBodyStore, fixture_html: Read
) -> None:
    fetches = [
        make_fetch(store, fixture_html("full_page"), fetch_id="fetch_a"),
        make_fetch(store, b"%PDF", fetch_id="fetch_b", content_type="application/pdf"),
        *non_page_fetches(store).values(),
        make_fetch(store, fixture_html("incomplete"), fetch_id="fetch_c"),
    ]

    result = extract_all(fetches, store, clock=clock)

    assert [d.fetch_id for d in result.documents] == ["fetch_a", "fetch_c"]
    assert [f.fetch_id for f in result.failures] == ["fetch_b"]
    assert sorted(s.reason for s in result.skipped) == [
        "no_stored_body",
        "not_successful_fetch",
        "not_successful_fetch",
        "robots_txt",
    ]


def test_one_bad_page_does_not_stop_the_audit(store: LocalBodyStore) -> None:
    broken = make_fetch(store, "<p>x</p>", fetch_id="fetch_bad")
    assert broken.body is not None
    (store.root / broken.body.sha256[:2] / broken.body.sha256).unlink()
    fetches = [broken, make_fetch(store, "<title>ok</title>", fetch_id="fetch_ok")]

    result = extract_all(fetches, store)
    assert [f.fetch_id for f in result.failures] == ["fetch_bad"]
    assert [d.fetch_id for d in result.documents] == ["fetch_ok"]


# --- artifacts ----------------------------------------------------------------


def test_artifacts_are_written_and_readable(
    store: LocalBodyStore, fixture_html: Read, tmp_path: Path
) -> None:
    fetches = [
        make_fetch(store, fixture_html("full_page"), fetch_id="fetch_a"),
        make_fetch(store, b"%PDF", fetch_id="fetch_b", content_type="application/pdf"),
        *non_page_fetches(store).values(),
    ]
    out = tmp_path / "ex"
    with ExtractionWriter(out) as sink:
        result = extract_all(fetches, store, sink=sink, clock=clock)

    assert read_documents(out / "documents.jsonl") == list(result.documents)
    failures = (out / "extraction_failures.jsonl").read_text().splitlines()
    assert json.loads(failures[0])["error_type"] == "unsupported_content_type"
    skipped = (out / "skipped_fetches.jsonl").read_text().splitlines()
    assert len(skipped) == 4
    summary = json.loads((out / "extraction_summary.json").read_text())
    assert summary["documents"] == 1 and summary["failures"] == 1
    assert summary["skipped"] == 4
    assert summary["failures_by_type"] == {"unsupported_content_type": 1}
    assert summary["extraction_version"] == EXTRACTION_VERSION


def test_records_are_durable_while_running(
    store: LocalBodyStore, tmp_path: Path
) -> None:
    class Spy(ExtractionWriter):
        def __init__(self, out: Path) -> None:
            super().__init__(out)
            self.seen: list[int] = []

        def write_document(self, record: Any) -> None:
            super().write_document(record)
            lines = (self.out_dir / "documents.jsonl").read_text().splitlines()
            self.seen.append(len(lines))

    fetches = [make_fetch(store, "<p>x</p>", fetch_id=f"fetch_{i}") for i in range(3)]
    with Spy(tmp_path / "ex") as sink:
        extract_all(fetches, store, sink=sink)
    assert sink.seen == [1, 2, 3]


def test_interrupted_run_keeps_earlier_documents(
    store: LocalBodyStore, tmp_path: Path
) -> None:
    fetches = [make_fetch(store, "<p>x</p>", fetch_id=f"fetch_{i}") for i in range(3)]
    real_get = store.get
    calls: list[str] = []

    def interrupting(ref: str) -> bytes:
        calls.append(ref)
        if len(calls) == 3:
            raise KeyboardInterrupt
        return real_get(ref)

    store.get = interrupting  # type: ignore[method-assign]
    out = tmp_path / "ex"
    with pytest.raises(KeyboardInterrupt), ExtractionWriter(out) as sink:
        extract_all(fetches, store, sink=sink)

    assert len(read_documents(out / "documents.jsonl")) == 2


def test_existing_extraction_is_never_overwritten(tmp_path: Path) -> None:
    ExtractionWriter(tmp_path).close()
    with pytest.raises(FileExistsError):
        ExtractionWriter(tmp_path)


def test_reader_ignores_a_torn_line_and_requires_a_version(
    store: LocalBodyStore, tmp_path: Path
) -> None:
    good = doc(
        extract_fetch(make_fetch(store, "<title>t</title>"), store)
    ).model_dump_json()
    path = tmp_path / "documents.jsonl"
    path.write_text(good + "\n" + good[:40], encoding="utf-8")
    assert len(read_documents(path)) == 1

    data = json.loads(good)
    del data["schema_version"]
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version"):
        read_documents(path)


# --- end to end: crawl a mock site, then extract it ---------------------------


def test_crawl_then_extract(
    site: MockSite, store: LocalBodyStore, tmp_path: Path
) -> None:
    site.add("/robots.txt", "User-agent: *\nDisallow:\n", content_type="text/plain")
    site.add(
        "/",
        '<html lang="en"><title>Home</title><h1>Welcome</h1><a href="/about">About</a>'
        '<script type="application/ld+json">{"@type":"Organization"}</script></html>',
    )
    site.add("/about", "<title>About us</title><p>We build things.</p>")
    audit = AuditRequest(
        audit_id="aud_e2e",
        target_domain="site.test",
        brand_name="Site",
        business_context="test",
        target_audience="testers",
        authorization_confirmed=True,
    )
    config = CrawlConfig(
        allowed_ports=frozenset({site.port}),
        min_request_interval_seconds=0,
        request_timeout_seconds=5,
        max_fetch_seconds=10,
    )
    fetcher = SafeFetcher(
        config,
        store,
        audit.audit_id,
        host_allowed=lambda h: host_in_scope(h, "site.test"),
        resolver=lambda host, port: ["127.0.0.1"],
        ip_policy=lambda ip: ip.is_loopback,
    )
    crawl_dir = tmp_path / "crawl"
    with ArtifactWriter(crawl_dir) as sink:
        Crawler(audit, config, fetcher, seed_url=site.url(), sink=sink).run()
    crawled = read_fetches(crawl_dir / "fetches.jsonl")

    with ExtractionWriter(tmp_path / "ex") as sink:
        result = extract_all(crawled, store, sink=sink)

    assert [s.reason for s in result.skipped] == ["robots_txt"]
    assert result.failures == ()
    by_path = {d.url.path: d for d in result.documents}
    assert by_path["/"].title == "Home" and by_path["/"].language == "en"
    assert by_path["/"].structured_data_types == ("Organization",)
    assert by_path["/"].links == (site.url("/about"),)
    assert by_path["/about"].text == "We build things."
    assert {d.audit_id for d in result.documents} == {"aud_e2e"}
    fetch_ids = {f.fetch_id for f in crawled}
    assert {d.fetch_id for d in result.documents} <= fetch_ids  # joinable to fetches


def test_cli_extracts_a_finished_crawl(
    store: LocalBodyStore, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    crawl_dir = tmp_path / "crawl"
    bodies = LocalBodyStore(crawl_dir / "bodies")
    fetch = make_fetch(bodies, "<title>From CLI</title>")
    with ArtifactWriter(crawl_dir) as sink:
        sink.write_fetch(fetch)

    assert main(["--crawl-dir", str(crawl_dir)]) == 0

    documents = read_documents(crawl_dir / "extraction" / "documents.jsonl")
    assert [d.title for d in documents] == ["From CLI"]
    assert "1 documents, 0 failures, 0 skipped" in capsys.readouterr().out


# --- rich extraction through the pipeline -------------------------------------


def test_documents_carry_the_rich_fields_and_detail_level(
    store: LocalBodyStore, fixture_html: Read
) -> None:
    fetch = make_fetch(
        store, fixture_html("rich_page"), url="https://www.example.com/p"
    )

    document = doc(extract_fetch(fetch, store, clock=clock))

    assert (
        document.detail_level == 2 and document.extraction_version == EXTRACTION_VERSION
    )
    assert document.viewport == "width=device-width, initial-scale=1"
    assert document.charset_declared == "utf-8"
    assert len(document.images) == 5 and len(document.anchors) == 8
    assert document.images[0].alt == "Our team" and document.images[0].width == 640
    assert document.anchors[1].rel == ("nofollow",)
    assert [m.kind for m in document.landmarks][:3] == ["banner", "navigation", "main"]
    assert document.tables[0].header_cells == ("Plan", "Price")
    assert [b.kind for b in document.lists] == ["ul", "ol", "dl"]
    assert [m.kind for m in document.media] == ["video", "audio", "video_embed"]
    assert str(document.url) == "https://www.example.com/p"  # provenance is unchanged
    assert document.fetch_id == fetch.fetch_id
    assert PageDocument.model_validate_json(document.model_dump_json()) == document


def test_rich_limits_are_reported_on_the_document(store: LocalBodyStore) -> None:
    images = "".join(f'<img src="/{i}.png" alt="a">' for i in range(10))
    document = doc(
        extract_fetch(make_fetch(store, images), store, ExtractionConfig(max_images=3))
    )
    assert len(document.images) == 3 and document.truncated_fields == ("images",)


@pytest.mark.parametrize(
    "name", ["rich_malformed", "rich_incomplete", "empty", "blank"]
)
def test_rich_fixtures_never_fail_extraction(
    store: LocalBodyStore, fixture_html: Read, name: str
) -> None:
    result = extract_fetch(make_fetch(store, fixture_html(name)), store)
    assert isinstance(result, PageDocument) and result.detail_level == 2


def test_empty_documents_have_empty_rich_fields(
    store: LocalBodyStore, fixture_html: Read
) -> None:
    document = doc(extract_fetch(make_fetch(store, fixture_html("empty")), store))
    assert document.images == () and document.anchors == () and document.landmarks == ()
    assert document.viewport is None and document.semantic_counts == {}
