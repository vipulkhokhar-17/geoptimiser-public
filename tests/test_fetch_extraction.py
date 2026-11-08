from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from geoptimiser.schemas import (
    ExtractionFailure,
    FetchRecord,
    Heading,
    PageDocument,
    RedirectHop,
    StoredBody,
    check_extraction_source,
)

AUDIT_ID = "aud_test_001"
STARTED = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
COMPLETED = STARTED + timedelta(milliseconds=350)
BODY = StoredBody(ref="bodies/ab/abcd.html", sha256="a" * 64, size_bytes=5120)


def make_fetch(**overrides: Any) -> FetchRecord:
    fields: dict[str, Any] = {
        "audit_id": AUDIT_ID,
        "fetch_id": "fetch_001",
        "requested_url": "https://example.com/pricing",
        "outcome": "success",
        "status_code": 200,
        "final_url": "https://example.com/pricing",
        "headers": {"Content-Type": "text/html; charset=utf-8"},
        "body": BODY,
        "started_at": STARTED,
        "completed_at": COMPLETED,
    }
    merged = fields | overrides
    if merged["outcome"] == "redirect_not_followed":
        merged = {"redirect_refusal_reason": "cross_domain"} | merged
    return FetchRecord(**merged)


def make_transport_error(**overrides: Any) -> FetchRecord:
    fields: dict[str, Any] = {
        "outcome": "transport_error",
        "status_code": None,
        "final_url": None,
        "headers": {},
        "body": None,
        "error_type": "timeout",
        "error_message": "No response within 10s",
    }
    return make_fetch(**(fields | overrides))


def make_document(**overrides: Any) -> PageDocument:
    fields: dict[str, Any] = {
        "audit_id": AUDIT_ID,
        "document_id": "doc_001",
        "fetch_id": "fetch_001",
        "url": "https://example.com/pricing",
        "extraction_version": "html-extractor:1",
        "title": "Pricing",
        "headings": [Heading(level=1, text="Pricing")],
        "text": "Plans start at $10 per month.",
    }
    return PageDocument(**(fields | overrides))


def make_extraction_failure(**overrides: Any) -> ExtractionFailure:
    fields: dict[str, Any] = {
        "audit_id": AUDIT_ID,
        "fetch_id": "fetch_001",
        "extraction_version": "html-extractor:1",
        "error_type": "unsupported_content_type",
        "error_message": "application/pdf is not handled by the HTML extractor",
    }
    return ExtractionFailure(**(fields | overrides))


REDIRECT = RedirectHop(
    url="https://example.com/old-pricing", status_code=301, location="/pricing"
)


@pytest.mark.parametrize(
    "instance",
    [
        make_fetch(),
        make_fetch(
            requested_url="https://example.com/old-pricing", redirects=[REDIRECT]
        ),
        make_transport_error(),
        make_document(),
        make_extraction_failure(),
    ],
    ids=lambda instance: type(instance).__name__,
)
def test_json_round_trip(instance: BaseModel) -> None:
    restored = type(instance).model_validate(instance.model_dump(mode="json"))

    assert restored == instance


@pytest.mark.parametrize(
    "model", [FetchRecord, RedirectHop, StoredBody, Heading, PageDocument]
)
def test_models_forbid_unknown_fields(model: type[BaseModel]) -> None:
    assert model.model_json_schema()["additionalProperties"] is False


# --- FetchRecord: successful fetches -------------------------------------------


def test_successful_fetch_without_body_needs_a_reason() -> None:
    fetch = make_fetch(
        status_code=204, body=None, body_not_stored_reason="empty_response"
    )

    assert fetch.body is None
    with pytest.raises(ValidationError, match="must say why"):
        make_fetch(status_code=204, body=None)


def test_stored_body_and_not_stored_reason_are_exclusive() -> None:
    with pytest.raises(ValidationError, match="cannot also have"):
        make_fetch(body_not_stored_reason="empty_response")


def test_truncated_body_is_flagged() -> None:
    assert not BODY.truncated
    assert make_fetch(body=BODY.model_copy(update={"truncated": True})).body.truncated


@pytest.mark.parametrize("outcome", ["success", "http_error"])
def test_refusal_reason_only_allowed_on_redirect_not_followed(outcome: str) -> None:
    status = 200 if outcome == "success" else 404
    with pytest.raises(ValidationError, match="redirect_refusal_reason"):
        make_fetch(
            outcome=outcome, status_code=status, redirect_refusal_reason="cross_domain"
        )


def test_redirect_not_followed_requires_a_reason() -> None:
    with pytest.raises(ValidationError, match="redirect_refusal_reason"):
        make_fetch(
            outcome="redirect_not_followed",
            status_code=302,
            body=None,
            redirect_refusal_reason=None,
        )


def test_transport_error_rejects_reasons() -> None:
    for field, reason in (
        ("body_not_stored_reason", "empty_response"),
        ("redirect_refusal_reason", "cross_domain"),
    ):
        with pytest.raises(ValidationError, match="must be empty"):
            make_transport_error(**{field: reason})


def test_schema_version_is_declared_and_checked() -> None:
    assert make_fetch().schema_version == 1
    assert make_fetch().model_dump()["schema_version"] == 1
    with pytest.raises(ValidationError):
        make_fetch(schema_version=2)


def test_successful_fetch_after_redirects() -> None:
    fetch = make_fetch(
        requested_url="https://example.com/old-pricing", redirects=[REDIRECT]
    )

    assert fetch.final_url != fetch.requested_url
    assert fetch.redirects[0].location == "/pricing"


def test_final_url_must_match_request_without_redirects() -> None:
    with pytest.raises(ValidationError, match="without redirects"):
        make_fetch(final_url="https://example.com/elsewhere")


def test_first_redirect_hop_must_start_at_requested_url() -> None:
    with pytest.raises(ValidationError, match="first redirect hop"):
        make_fetch(redirects=[REDIRECT])


def test_redirect_hop_must_be_3xx() -> None:
    with pytest.raises(ValidationError):
        RedirectHop(url="https://example.com/", status_code=200, location="/x")


# --- FetchRecord: HTTP error responses and unfollowed redirects ------------------


@pytest.mark.parametrize("status_code", [400, 404, 429, 500, 503, 599])
def test_http_error_records_the_response(status_code: int) -> None:
    fetch = make_fetch(outcome="http_error", status_code=status_code, body=None)

    assert fetch.status_code == status_code
    assert fetch.error_type is None


def test_http_error_may_keep_the_error_page_body() -> None:
    assert make_fetch(outcome="http_error", status_code=404).body == BODY


def test_redirect_not_followed_records_the_3xx_response() -> None:
    fetch = make_fetch(
        outcome="redirect_not_followed",
        status_code=302,
        headers={"Location": "http://10.0.0.5/admin"},
        body=None,
        redirect_refusal_reason="blocked_address",
    )

    assert fetch.headers["location"] == "http://10.0.0.5/admin"


@pytest.mark.parametrize(
    ("outcome", "status_code"),
    [
        ("success", 404),
        ("success", 302),
        ("http_error", 200),
        ("http_error", 302),
        ("redirect_not_followed", 200),
        ("redirect_not_followed", 404),
    ],
)
def test_outcome_must_match_status_code(outcome: str, status_code: int) -> None:
    with pytest.raises(ValidationError, match="requires a status code"):
        make_fetch(outcome=outcome, status_code=status_code)


@pytest.mark.parametrize("missing", ["status_code", "final_url"])
@pytest.mark.parametrize("outcome", ["success", "http_error", "redirect_not_followed"])
def test_response_outcomes_require_status_and_final_url(
    outcome: str, missing: str
) -> None:
    valid_status = {"success": 200, "http_error": 404, "redirect_not_followed": 301}
    fields = {"outcome": outcome, "status_code": valid_status[outcome]}

    with pytest.raises(ValidationError, match="response was received"):
        make_fetch(**(fields | {missing: None}))


@pytest.mark.parametrize(
    "error_fields",
    [{"error_type": "timeout"}, {"error_message": "boom"}],
)
def test_response_outcomes_reject_transport_error_fields(
    error_fields: dict[str, str],
) -> None:
    with pytest.raises(ValidationError, match="only allowed for 'transport_error'"):
        make_fetch(outcome="http_error", status_code=500, **error_fields)


@pytest.mark.parametrize("status_code", [99, 600])
def test_status_code_outside_http_range_is_rejected(status_code: int) -> None:
    with pytest.raises(ValidationError):
        make_fetch(status_code=status_code)


# --- FetchRecord: transport failures (no HTTP response) --------------------------


def test_transport_error_has_no_status_code() -> None:
    fetch = make_transport_error(error_type="dns", error_message="NXDOMAIN")

    assert fetch.status_code is None
    assert fetch.final_url is None


def test_too_many_redirects_keeps_hops_without_a_final_response() -> None:
    fetch = make_transport_error(
        requested_url="https://example.com/old-pricing",
        redirects=[REDIRECT],
        error_type="too_many_redirects",
        error_message="Redirect limit reached",
    )

    assert fetch.redirects == (REDIRECT,)
    assert fetch.status_code is None


@pytest.mark.parametrize(
    "response_field",
    [
        {"status_code": 200},
        {"final_url": "https://example.com/pricing"},
        {"headers": {"content-type": "text/html"}},
        {"body": BODY},
    ],
)
def test_transport_error_cannot_carry_response_data(
    response_field: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError, match="no HTTP response was received"):
        make_transport_error(**response_field)


@pytest.mark.parametrize("missing", ["error_type", "error_message"])
def test_transport_error_requires_type_and_message(missing: str) -> None:
    with pytest.raises(ValidationError, match="requires error_type and error_message"):
        make_transport_error(**{missing: None})


def test_transport_error_type_is_closed() -> None:
    with pytest.raises(ValidationError):
        make_transport_error(error_type="gremlins")


# --- FetchRecord: metadata ------------------------------------------------------


def test_completed_before_started_is_rejected() -> None:
    with pytest.raises(ValidationError, match="completed_at"):
        make_fetch(completed_at=STARTED - timedelta(seconds=1))


def test_instant_fetch_is_allowed() -> None:
    assert make_fetch(completed_at=STARTED).completed_at == STARTED


def test_fetch_timestamps_are_required() -> None:
    with pytest.raises(ValidationError, match="started_at"):
        FetchRecord(
            audit_id=AUDIT_ID,
            fetch_id="fetch_001",
            requested_url="https://example.com/",
            outcome="success",
            status_code=200,
            final_url="https://example.com/",
            completed_at=COMPLETED,
        )


def test_header_names_are_lowercased() -> None:
    fetch = make_fetch(headers={"Content-Type": "text/html", "X-Robots-Tag": "noai"})

    assert fetch.headers == {"content-type": "text/html", "x-robots-tag": "noai"}


def test_header_names_colliding_by_case_are_rejected() -> None:
    with pytest.raises(ValidationError, match="unique"):
        make_fetch(headers={"Content-Type": "text/html", "content-type": "text/plain"})


@pytest.mark.parametrize(
    "header", ["Set-Cookie", "cookie", "Authorization", "Proxy-Authorization"]
)
def test_credential_bearing_headers_are_rejected(header: str) -> None:
    with pytest.raises(ValidationError, match="must not be stored"):
        make_fetch(headers={header: "secret"})


@pytest.mark.parametrize(
    "body_fields",
    [
        {"sha256": "A" * 64},
        {"sha256": "a" * 63},
        {"size_bytes": -1},
        {"ref": " "},
    ],
)
def test_stored_body_reference_is_validated(body_fields: dict[str, Any]) -> None:
    fields = {"ref": "bodies/x", "sha256": "a" * 64, "size_bytes": 1}

    with pytest.raises(ValidationError):
        StoredBody(**(fields | body_fields))


def test_requested_url_must_be_http() -> None:
    with pytest.raises(ValidationError):
        make_fetch(requested_url="ftp://example.com/file")


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8080/",
        "http://127.0.0.1/",
        "http://10.0.0.5/admin",
        "http://169.254.169.254/latest/meta-data/",
    ],
)
def test_fetch_url_check_is_not_ssrf_protection(url: str) -> None:
    # The record describes what was fetched; deciding what may be fetched is
    # the Stage 01 crawler's job.
    fetch = make_fetch(requested_url=url, final_url=url)

    assert str(fetch.requested_url) == url


# --- PageDocument -----------------------------------------------------------------


def test_empty_text_is_a_measurement_not_a_failure() -> None:
    # e.g. a JavaScript-only page: extraction succeeded and found no text.
    document = make_document(text="", headings=[], title=None)

    assert document.text == ""


def test_document_keeps_malformed_observed_urls_as_raw_strings() -> None:
    document = make_document(
        canonical_url="htp:/broken", links=["javascript:void(0)", "/relative"]
    )

    assert document.canonical_url == "htp:/broken"
    assert document.links == ("javascript:void(0)", "/relative")


@pytest.mark.parametrize("level", [0, 7])
def test_heading_level_is_bounded(level: int) -> None:
    with pytest.raises(ValidationError):
        Heading(level=level, text="Title")


def test_empty_heading_text_is_recorded() -> None:
    assert Heading(level=2, text="").text == ""


@pytest.mark.parametrize("missing", ["fetch_id", "extraction_version"])
def test_document_requires_lineage(missing: str) -> None:
    fields = make_document().model_dump()
    del fields[missing]

    with pytest.raises(ValidationError, match=missing):
        PageDocument(**fields)


def test_document_has_no_fetch_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        make_document(status_code=200)


# --- ExtractionFailure ------------------------------------------------------------


def test_extraction_failure_requires_message() -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        make_extraction_failure(error_message="  ")


def test_extraction_failure_type_is_closed() -> None:
    with pytest.raises(ValidationError):
        make_extraction_failure(error_type="empty_content")


# --- check_extraction_source ------------------------------------------------------


@pytest.mark.parametrize("result", [make_document(), make_extraction_failure()])
def test_successful_fetch_with_body_is_extractable(
    result: PageDocument | ExtractionFailure,
) -> None:
    check_extraction_source(make_fetch(), result)


def test_document_after_redirect_uses_final_url() -> None:
    fetch = make_fetch(
        requested_url="https://example.com/old-pricing", redirects=[REDIRECT]
    )

    check_extraction_source(fetch, make_document())


@pytest.mark.parametrize(
    "fetch",
    [
        make_fetch(outcome="http_error", status_code=404),
        make_fetch(outcome="redirect_not_followed", status_code=301),
        make_transport_error(),
        make_fetch(status_code=204, body=None, body_not_stored_reason="empty_response"),
    ],
    ids=["http_error", "redirect_not_followed", "transport_error", "no_body"],
)
@pytest.mark.parametrize("result", [make_document(), make_extraction_failure()])
def test_unextractable_fetches_are_rejected(
    fetch: FetchRecord, result: PageDocument | ExtractionFailure
) -> None:
    with pytest.raises(ValueError, match="only successful fetches"):
        check_extraction_source(fetch, result)


@pytest.mark.parametrize(
    "mismatch", [{"fetch_id": "fetch_999"}, {"audit_id": "aud_other"}]
)
def test_result_must_reference_the_fetch(mismatch: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="does not reference this fetch"):
        check_extraction_source(make_fetch(), make_document(**mismatch))


def test_document_url_must_equal_final_url() -> None:
    with pytest.raises(ValueError, match="final_url"):
        check_extraction_source(
            make_fetch(), make_document(url="https://example.com/other")
        )


# --- PageDocument: Stage 02 measurement and provenance fields -----------------------


def test_new_document_fields_default_to_absent_and_untruncated() -> None:
    document = make_document()

    assert document.meta_robots is None and document.encoding is None
    assert document.structured_data_errors == 0 and document.structured_data_types == ()
    assert document.source_truncated is False and document.truncated_fields == ()


def test_document_records_limits_and_structured_data_signals() -> None:
    document = make_document(
        meta_robots="noindex",
        structured_data_errors=2,
        structured_data_types=["Organization", "https://schema.org/Product"],
        encoding="utf-8",
        source_truncated=True,
        truncated_fields=["text", "links"],
    )

    assert document.truncated_fields == ("text", "links")
    assert document.structured_data_types[0] == "Organization"
    assert PageDocument.model_validate_json(document.model_dump_json()) == document


def test_structured_data_error_count_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        make_document(structured_data_errors=-1)


def test_truncated_fields_are_a_closed_set() -> None:
    with pytest.raises(ValidationError):
        make_document(truncated_fields=["headline"])


# --- PageDocument: rich fields and detail level ---------------------------------------


def test_level_one_documents_cannot_carry_rich_fields() -> None:
    assert make_document().detail_level == 1  # an older extractor's document
    for field, value in [
        ("viewport", "width=device-width"),
        ("charset_declared", "utf-8"),
        ("images", [{"src": "https://e.com/a.png"}]),
        ("anchors", [{"href": "https://e.com/", "text": "x", "internal": True}]),
        ("landmarks", [{"kind": "main", "source": "tag"}]),
        ("semantic_counts", {"main": 1}),
        ("boilerplate_chars", 5),
        ("main_chars", 5),
        ("hidden_chars", 5),
        ("tables", [{}]),
        ("lists", [{"kind": "ul"}]),
        ("media", [{"kind": "video"}]),
    ]:
        with pytest.raises(ValidationError, match="detail_level"):
            make_document(**{field: value})


def test_level_two_documents_round_trip_with_rich_fields() -> None:
    document = make_document(
        detail_level=2,
        viewport="width=device-width",
        images=[
            {"src": "https://e.com/a.png", "alt": "", "decorative": True, "width": 10}
        ],
        anchors=[
            {
                "href": "https://e.com/",
                "text": "Home",
                "rel": ["nofollow"],
                "internal": True,
            }
        ],
        landmarks=[{"kind": "main", "source": "tag", "text_chars": 12}],
        semantic_counts={"main": 1},
        tables=[
            {"caption": "T", "header_cells": ["a"], "rows": [["1"]], "row_count": 1}
        ],
        lists=[{"kind": "ol", "items": ["x"], "item_count": 1}],
        media=[
            {"kind": "video", "has_captions": False},
            {"kind": "video_embed"},
        ],
        truncated_fields=["images", "tables"],
    )
    assert document.images[0].alt == "" and document.images[0].decorative
    assert document.anchors[0].rel == ("nofollow",)
    assert document.media[1].has_captions is None  # unknown, not False
    assert PageDocument.model_validate_json(document.model_dump_json()) == document


@pytest.mark.parametrize(
    "bad",
    [
        {"images": [{"width": -1}]},
        {"images": [{"unknown": 1}]},
        {"anchors": [{"href": "https://e.com/", "text": "x"}]},  # internal is required
        {"landmarks": [{"kind": "sidebar", "source": "tag"}]},
        {"lists": [{"kind": "table"}]},
        {"media": [{"kind": "gif"}]},
        {"truncated_fields": ["headline"]},
        {"main_chars": -1},
    ],
)
def test_rich_models_are_strict(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        make_document(detail_level=2, **bad)
