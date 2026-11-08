from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from geoptimiser.schemas import (
    AuditRequest,
    Citation,
    EvidenceRef,
    ExtractionFailure,
    FeatureResult,
    FetchRecord,
    Finding,
    Heading,
    PageDocument,
    Recommendation,
    RedirectHop,
    SchemaModel,
    StoredBody,
    VisibilityObservation,
)

AUDIT_ID = "aud_test_001"
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

AUDIT_REQUEST = AuditRequest(
    target_domain="example.com",
    brand_name="Example",
    business_context="B2B invoicing software",
    target_audience="Finance teams",
    competitor_domains=["rival.io"],
    authorization_confirmed=True,
)
REDIRECT = RedirectHop(url="https://example.com/old", status_code=301, location="/new")
BODY = StoredBody(ref="bodies/x", sha256="a" * 64, size_bytes=10)
FETCH = FetchRecord(
    audit_id=AUDIT_ID,
    fetch_id="fetch_001",
    requested_url="https://example.com/old",
    outcome="success",
    status_code=200,
    final_url="https://example.com/new",
    redirects=[REDIRECT],
    headers={"Content-Type": "text/html"},
    body=BODY,
    started_at=NOW,
    completed_at=NOW,
)
TIMEOUT = FetchRecord(
    audit_id=AUDIT_ID,
    fetch_id="fetch_002",
    requested_url="https://example.com/slow",
    outcome="transport_error",
    error_type="timeout",
    error_message="No response within 10s",
    started_at=NOW,
    completed_at=NOW,
)
DOCUMENT = PageDocument(
    audit_id=AUDIT_ID,
    document_id="doc_001",
    fetch_id="fetch_001",
    url="https://example.com/new",
    extraction_version="html-extractor:1",
    headings=[Heading(level=1, text="Pricing")],
    links=["/signup"],
    structured_data=[{"@type": "Organization"}],
)
EXTRACTION_FAILURE = ExtractionFailure(
    audit_id=AUDIT_ID,
    fetch_id="fetch_001",
    extraction_version="html-extractor:1",
    error_type="parse_error",
    error_message="Unclosed tag",
)
EVIDENCE = EvidenceRef(
    evidence_id="ev_1",
    source_url="https://example.com",
    snippet="Example helps finance teams.",
    source_type="website",
)
FEATURE = FeatureResult(
    audit_id=AUDIT_ID,
    feature_id="TECH-001",
    feature_version=1,
    category="technical",
    status="fail",
    evidence=[EVIDENCE],
    measurement_method="GET /sitemap.xml",
)
OBSERVATION = VisibilityObservation(
    audit_id=AUDIT_ID,
    query_id="Q-001",
    query_set_version=1,
    provider="mock",
    model="mock-model",
    query="best invoicing software",
    response_text="Example is popular.",
    citations=[Citation(url="https://example.com")],
    brand_mentioned=True,
)
FINDING = Finding(
    audit_id=AUDIT_ID,
    finding_id="FND-001",
    title="No XML sitemap",
    description="The site does not expose /sitemap.xml.",
    category="technical",
    severity="high",
    basis="measured",
    evidence_ids=["ev_1"],
    measurement_method="GET /sitemap.xml returned 404",
    confidence=0.9,
    verification_criteria=["GET /sitemap.xml returns 200"],
)
RECOMMENDATION = Recommendation(
    audit_id=AUDIT_ID,
    recommendation_id="REC-001",
    title="Publish an XML sitemap",
    rationale="Crawlers cannot discover all pages",
    proposed_change="Generate /sitemap.xml",
    finding_ids=["FND-001"],
    evidence_ids=["ev_1"],
    expected_impact_direction="positive",
    confidence=0.6,
    priority="P1",
    estimated_effort="small",
    verification_plan=["Rerun TECH-001"],
)


def _all_subclasses(base: type[SchemaModel]) -> list[type[SchemaModel]]:
    found: list[type[SchemaModel]] = []
    for sub in base.__subclasses__():
        found.append(sub)
        found.extend(_all_subclasses(sub))
    return found


def test_every_shared_model_is_frozen() -> None:
    # Guards against a future model overriding the base config.
    models = _all_subclasses(SchemaModel)

    # Modules imported by other tests add their own models; every one must be frozen.
    assert len(models) >= 20
    assert all(model.model_config.get("frozen") is True for model in models)


@pytest.mark.parametrize(
    ("instance", "field", "value"),
    [
        (AUDIT_REQUEST, "target_domain", "other.com"),
        (REDIRECT, "status_code", 302),
        (BODY, "sha256", "b" * 64),
        (FETCH, "status_code", 404),
        (TIMEOUT, "status_code", 200),
        (DOCUMENT, "text", "changed"),
        (EXTRACTION_FAILURE, "error_type", "other"),
        (EVIDENCE, "snippet", "changed"),
        (FEATURE, "status", "pass"),
        (OBSERVATION, "brand_mentioned", False),
        (FINDING, "evidence_ids", ()),
        (RECOMMENDATION, "confidence", 5.0),
    ],
    ids=lambda value: type(value).__name__ if isinstance(value, SchemaModel) else "",
)
def test_field_reassignment_is_rejected(
    instance: SchemaModel, field: str, value: Any
) -> None:
    before = getattr(instance, field)

    with pytest.raises(ValidationError, match="frozen"):
        setattr(instance, field, value)
    assert getattr(instance, field) == before


@pytest.mark.parametrize(
    ("instance", "field"),
    [
        (AUDIT_REQUEST, "competitor_domains"),
        (FETCH, "redirects"),
        (DOCUMENT, "headings"),
        (DOCUMENT, "links"),
        (DOCUMENT, "structured_data"),
        (FEATURE, "evidence"),
        (OBSERVATION, "citations"),
        (OBSERVATION, "competitors_mentioned"),
        (FINDING, "evidence_ids"),
        (FINDING, "verification_criteria"),
        (RECOMMENDATION, "finding_ids"),
        (RECOMMENDATION, "evidence_ids"),
        (RECOMMENDATION, "verification_plan"),
    ],
)
def test_collections_cannot_be_mutated_in_place(
    instance: SchemaModel, field: str
) -> None:
    # With list fields, .clear() would empty a min_length=1 list or let
    # .append() add an unvalidated value, behind the validators' back.
    value = getattr(instance, field)

    assert isinstance(value, tuple)
    with pytest.raises(AttributeError):
        value.append("unvalidated")  # type: ignore[attr-defined]


def test_headers_are_read_only() -> None:
    with pytest.raises(TypeError):
        FETCH.headers["set-cookie"] = "session=1"  # type: ignore[index]
    assert "set-cookie" not in FETCH.headers


def test_default_headers_are_read_only() -> None:
    with pytest.raises(TypeError):
        TIMEOUT.headers["content-type"] = "text/html"  # type: ignore[index]
    assert not TIMEOUT.headers


def test_read_only_headers_serialize_as_plain_dict() -> None:
    assert FETCH.model_dump()["headers"] == {"content-type": "text/html"}
    assert FetchRecord.model_validate_json(FETCH.model_dump_json()) == FETCH


def test_model_copy_update_bypasses_validation() -> None:
    # Documented Pydantic behaviour that freezing does not change: the copy
    # breaks the transport_error invariant without raising.
    copy = TIMEOUT.model_copy(update={"status_code": 404})

    assert (copy.outcome, copy.status_code) == ("transport_error", 404)
    with pytest.raises(ValidationError, match="no HTTP response was received"):
        FetchRecord.model_validate(copy.model_dump())


def test_documented_update_pattern_validates_the_new_record() -> None:
    with pytest.raises(ValidationError, match="no HTTP response was received"):
        FetchRecord.model_validate(TIMEOUT.model_dump() | {"status_code": 404})

    updated = PageDocument.model_validate(DOCUMENT.model_dump() | {"text": "New"})
    assert updated.text == "New"
    assert DOCUMENT.text == ""


def test_raw_json_values_are_not_deep_frozen() -> None:
    # Documented limitation: raw JSON-LD dicts stay mutable. No schema
    # invariant depends on their contents.
    document = PageDocument.model_validate(DOCUMENT.model_dump())

    document.structured_data[0]["@type"] = "Person"

    assert document.structured_data[0]["@type"] == "Person"
