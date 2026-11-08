import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from geoptimiser.schemas import (
    AuditRequest,
    Citation,
    EvidenceRef,
    FeatureResult,
    Finding,
    Recommendation,
    VisibilityObservation,
    normalize_domain,
)

AUDIT_ID = "aud_test_001"


def make_audit_request(**overrides: Any) -> AuditRequest:
    fields: dict[str, Any] = {
        "target_domain": "example.com",
        "brand_name": "Example",
        "business_context": "B2B invoicing software",
        "target_audience": "Finance teams at mid-size companies",
        "authorization_confirmed": True,
    }
    return AuditRequest(**(fields | overrides))


def make_feature_result(**overrides: Any) -> FeatureResult:
    fields: dict[str, Any] = {
        "audit_id": AUDIT_ID,
        "feature_id": "TECH-001",
        "feature_version": 1,
        "category": "technical",
        "status": "fail",
        "observed_value": False,
        "expected_value": True,
        "severity": "high",
        "measurement_method": "Check whether an accessible sitemap exists",
    }
    return FeatureResult(**(fields | overrides))


def make_observation(**overrides: Any) -> VisibilityObservation:
    fields: dict[str, Any] = {
        "audit_id": AUDIT_ID,
        "query_id": "Q-001",
        "query_set_version": 1,
        "provider": "mock",
        "model": "mock-model",
        "query": "best invoicing software for startups",
        "response_text": "Example and Rival are popular choices.",
        "citations": [Citation(url="https://example.com/pricing")],
        "brand_mentioned": True,
        "competitors_mentioned": ["Rival"],
    }
    return VisibilityObservation(**(fields | overrides))


def make_finding(**overrides: Any) -> Finding:
    fields: dict[str, Any] = {
        "audit_id": AUDIT_ID,
        "finding_id": "FND-001",
        "title": "No XML sitemap",
        "description": "The site does not expose a sitemap at /sitemap.xml.",
        "category": "technical",
        "severity": "high",
        "basis": "measured",
        "feature_ids": ["TECH-001"],
        "evidence_ids": ["ev_sitemap_404"],
        "measurement_method": "HTTP GET /sitemap.xml returned 404",
        "confidence": 0.9,
        "verification_criteria": ["GET /sitemap.xml returns 200 with valid XML"],
    }
    return Finding(**(fields | overrides))


def make_recommendation(**overrides: Any) -> Recommendation:
    fields: dict[str, Any] = {
        "audit_id": AUDIT_ID,
        "recommendation_id": "REC-001",
        "title": "Publish an XML sitemap",
        "rationale": "Crawlers cannot discover all pages without a sitemap",
        "proposed_change": "Generate /sitemap.xml listing canonical pages",
        "finding_ids": ["FND-001"],
        "evidence_ids": ["ev_sitemap_404"],
        "expected_impact_direction": "positive",
        "confidence": 0.6,
        "priority": "P1",
        "estimated_effort": "small",
        "verification_plan": ["Rerun TECH-001 and confirm status 'pass'"],
    }
    return Recommendation(**(fields | overrides))


# --- Cross-cutting conventions ---------------------------------------------


@pytest.mark.parametrize(
    "instance",
    [
        make_audit_request(competitor_domains=["rival.io"]),
        EvidenceRef(
            evidence_id="ev_1",
            source_url="https://example.com",
            snippet="Example helps finance teams.",
            source_type="website",
        ),
        make_feature_result(),
        make_observation(),
        make_finding(),
        make_recommendation(),
    ],
    ids=lambda instance: type(instance).__name__,
)
def test_models_json_round_trip(instance: BaseModel) -> None:
    payload = instance.model_dump(mode="json")
    restored = type(instance).model_validate(payload)

    assert restored == instance


@pytest.mark.parametrize(
    "model",
    [
        AuditRequest,
        EvidenceRef,
        FeatureResult,
        Citation,
        VisibilityObservation,
        Finding,
        Recommendation,
    ],
)
def test_models_export_json_schema(model: type[BaseModel]) -> None:
    schema = model.model_json_schema()

    assert schema["additionalProperties"] is False


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        make_feature_result(sevrity="low")


def make_evidence(**overrides: Any) -> EvidenceRef:
    fields: dict[str, Any] = {
        "evidence_id": "ev_1",
        "source_url": "https://example.com",
        "snippet": "Example helps finance teams.",
        "source_type": "website",
    }
    return EvidenceRef(**(fields | overrides))


def test_default_timestamp_is_utc() -> None:
    assert make_evidence().retrieved_at.tzinfo == UTC


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        make_evidence(retrieved_at=datetime(2026, 1, 1, 12, 0))


def test_offset_timestamp_is_normalized_to_utc() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    evidence = make_evidence(retrieved_at=datetime(2026, 1, 1, 17, 30, tzinfo=ist))

    assert evidence.retrieved_at == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert evidence.retrieved_at.tzinfo == UTC


@pytest.mark.parametrize("bad_id", ["", " TECH-001", "TECH 001", "-leading", "a" * 129])
def test_identifiers_are_constrained(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        make_feature_result(feature_id=bad_id)


# --- AuditRequest ------------------------------------------------------------


def test_audit_request_generates_unique_audit_ids() -> None:
    first, second = make_audit_request(), make_audit_request()

    assert first.audit_id.startswith("aud_")
    assert first.audit_id != second.audit_id


def test_audit_request_requires_explicit_target_domain() -> None:
    with pytest.raises(ValidationError, match="target_domain"):
        AuditRequest(
            brand_name="Example",
            business_context="B2B invoicing software",
            target_audience="Finance teams",
            authorization_confirmed=True,
        )


def test_audit_request_requires_authorization() -> None:
    with pytest.raises(ValidationError, match="must attest"):
        make_audit_request(authorization_confirmed=False)


@pytest.mark.parametrize("value", [1, 1.0, "true", "yes", None])
def test_authorization_attestation_must_be_boolean_true(value: Any) -> None:
    # Literal[True] would accept 1 because 1 == True in Python.
    with pytest.raises(ValidationError, match="authorization_confirmed"):
        make_audit_request(authorization_confirmed=value)


def test_authorization_attestation_from_json() -> None:
    payload = make_audit_request().model_dump(mode="json")

    assert AuditRequest.model_validate_json(json.dumps(payload)).authorization_confirmed
    payload["authorization_confirmed"] = 1
    with pytest.raises(ValidationError, match="authorization_confirmed"):
        AuditRequest.model_validate_json(json.dumps(payload))


def test_authorization_attestation_is_documented_as_unverified() -> None:
    schema = AuditRequest.model_json_schema()
    description = schema["properties"]["authorization_confirmed"]["description"]

    assert "attestation" in description
    assert "not a security control" in description.lower()


@pytest.mark.parametrize("blank_field", ["brand_name", "business_context"])
def test_audit_request_rejects_blank_context(blank_field: str) -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        make_audit_request(**{blank_field: "   "})


def test_audit_request_normalizes_domains() -> None:
    request = make_audit_request(
        target_domain="  Example.COM. ", competitor_domains=["Rival.io"]
    )

    assert request.target_domain == "example.com"
    assert request.competitor_domains == ("rival.io",)


def test_audit_request_rejects_target_listed_as_competitor() -> None:
    with pytest.raises(ValidationError, match="competitor"):
        make_audit_request(competitor_domains=["EXAMPLE.com"])


def test_audit_request_rejects_duplicate_competitors() -> None:
    with pytest.raises(ValidationError, match="duplicates"):
        make_audit_request(competitor_domains=["rival.io", "Rival.io"])


def test_audit_request_allows_no_competitors() -> None:
    assert make_audit_request().competitor_domains == ()


def test_audit_request_has_no_schema_level_competitor_cap() -> None:
    # Operational limits belong to configurable audit settings, not the schema.
    many = [f"rival{i}.io" for i in range(50)]

    request = make_audit_request(competitor_domains=many)

    assert request.competitor_domains == tuple(many)


def test_audit_request_validates_every_competitor_domain() -> None:
    with pytest.raises(ValidationError, match="competitor_domains.1"):
        make_audit_request(competitor_domains=["rival.io", "https://other.io"])


@pytest.mark.parametrize(
    "domain",
    ["example.com", "sub.example.co.uk", "my-site.io", "xn--mnchen-3ya.de"],
)
def test_normalize_domain_accepts_valid_domains(domain: str) -> None:
    assert normalize_domain(domain) == domain


@pytest.mark.parametrize(
    "domain",
    [
        "",
        "localhost",
        "https://example.com",
        "example.com/path",
        "example.com:8080",
        "user@example.com",
        "192.168.1.10",
        "[::1]",
        "exa mple.com",
        "-example.com",
        "example-.com",
        "example..com",
        "münchen.de",
        "a" * 64 + ".com",
    ],
)
def test_normalize_domain_rejects_invalid_domains(domain: str) -> None:
    with pytest.raises(ValueError):
        normalize_domain(domain)


@pytest.mark.parametrize(
    "domain", ["app.localhost", "localtest.me", "metadata.google.internal"]
)
def test_normalize_domain_does_not_resolve_or_block_private_names(
    domain: str,
) -> None:
    # These may resolve to loopback/private addresses. Blocking them requires
    # DNS resolution and IP checks, which belong to the Stage 01 crawler.
    assert normalize_domain(domain) == domain


# --- EvidenceRef ----------------------------------------------------------------


def test_evidence_ref_rejects_blank_snippet() -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        EvidenceRef(
            evidence_id="ev_1",
            source_url="https://example.com",
            snippet="  ",
            source_type="website",
        )


def test_evidence_ref_rejects_unknown_source_type() -> None:
    with pytest.raises(ValidationError):
        EvidenceRef(
            evidence_id="ev_1",
            source_url="https://example.com",
            snippet="text",
            source_type="rumour",  # type: ignore[arg-type]
        )


# --- FeatureResult ------------------------------------------------------------


def test_feature_status_cannot_be_arbitrary() -> None:
    with pytest.raises(ValidationError):
        make_feature_result(status="probably_bad")


def test_feature_result_requires_positive_version() -> None:
    with pytest.raises(ValidationError):
        make_feature_result(feature_version=0)


@pytest.mark.parametrize("status", ["not_measured", "not_applicable"])
def test_unmeasured_feature_has_no_observed_value(status: str) -> None:
    result = make_feature_result(status=status, observed_value=None)

    assert result.observed_value is None
    with pytest.raises(ValidationError, match="nothing was measured"):
        make_feature_result(status=status, observed_value=False)


def test_measured_feature_may_observe_none() -> None:
    result = make_feature_result(observed_value=None)

    assert result.status == "fail"
    assert result.observed_value is None


def test_feature_error_requires_message() -> None:
    result = make_feature_result(
        status="error", observed_value=None, error_message="Timeout after 10s"
    )

    assert result.error_message == "Timeout after 10s"
    with pytest.raises(ValidationError, match="requires an error_message"):
        make_feature_result(status="error", observed_value=None)


def test_feature_error_message_only_allowed_for_errors() -> None:
    with pytest.raises(ValidationError, match="only allowed"):
        make_feature_result(error_message="unexpected")


# --- VisibilityObservation ----------------------------------------------------


def test_observation_defaults_to_unannotated() -> None:
    observation = make_observation(brand_mentioned=None)

    assert observation.brand_mentioned is None


def test_failed_collection_is_not_a_negative_result() -> None:
    observation = make_observation(
        collection_status="error",
        error_message="HTTP 429 from provider",
        response_text="",
        citations=[],
        brand_mentioned=None,
        competitors_mentioned=[],
    )

    assert observation.brand_mentioned is None
    with pytest.raises(ValidationError, match="not a negative result"):
        make_observation(
            collection_status="error",
            error_message="HTTP 429 from provider",
            response_text="",
            citations=[],
            brand_mentioned=False,
            competitors_mentioned=[],
        )


def test_skipped_collection_needs_no_response() -> None:
    observation = make_observation(
        collection_status="skipped",
        response_text="",
        citations=[],
        brand_mentioned=None,
        competitors_mentioned=[],
    )

    assert observation.collection_status == "skipped"


def test_observation_error_requires_message() -> None:
    with pytest.raises(ValidationError, match="requires an error_message"):
        make_observation(
            collection_status="error",
            response_text="",
            citations=[],
            brand_mentioned=None,
            competitors_mentioned=[],
        )


def test_successful_observation_rejects_error_message() -> None:
    with pytest.raises(ValidationError, match="not allowed"):
        make_observation(error_message="should not be here")


def test_observation_requires_query_set_version() -> None:
    with pytest.raises(ValidationError, match="query_set_version"):
        VisibilityObservation(
            audit_id=AUDIT_ID,
            query_id="Q-001",
            provider="mock",
            model="mock-model",
            query="q",
        )


# --- Finding ------------------------------------------------------------------


def test_finding_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="evidence_ids"):
        make_finding(evidence_ids=[])


def test_finding_requires_verification_criteria() -> None:
    with pytest.raises(ValidationError, match="verification_criteria"):
        make_finding(verification_criteria=[])


def test_finding_basis_distinguishes_model_judgement() -> None:
    finding = make_finding(basis="model_judgement", feature_ids=[], confidence=0.4)

    assert finding.basis == "model_judgement"
    with pytest.raises(ValidationError):
        make_finding(basis="gut_feeling")


@pytest.mark.parametrize("confidence", [-0.1, 1.01])
def test_finding_confidence_is_bounded(confidence: float) -> None:
    with pytest.raises(ValidationError):
        make_finding(confidence=confidence)


# --- Recommendation -----------------------------------------------------------


def test_recommendation_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        make_recommendation(confidence=1.4)


@pytest.mark.parametrize("field", ["finding_ids", "evidence_ids", "verification_plan"])
def test_recommendation_requires_traceability(field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        make_recommendation(**{field: []})


def test_recommendation_rejects_blank_verification_step() -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        make_recommendation(verification_plan=[" "])


def test_recommendation_records_direction_not_magnitude() -> None:
    with pytest.raises(ValidationError):
        make_recommendation(expected_impact_direction="+30% citations")


# --- Stage 03 additions to FeatureResult and Finding ----------------------------------

_RESULT = {
    "audit_id": "aud_1",
    "feature_id": "F021",
    "feature_version": 1,
    "category": "C",
    "status": "pass",
    "measurement_method": "m",
}
_FINDING = {
    "audit_id": "aud_1",
    "finding_id": "fnd_1",
    "title": "t",
    "description": "d",
    "category": "C",
    "severity": "low",
    "feature_ids": ["F023"],
    "evidence_ids": ["ev_1"],
    "measurement_method": "m",
    "confidence": 0.5,
    "verification_criteria": ["v"],
}


def test_feature_result_new_fields_are_optional_for_old_records() -> None:
    result = FeatureResult(**_RESULT)
    assert result.scope == "audit" and result.subject_url is None
    assert result.is_heuristic is False and result.implementation_status is None


def test_finding_can_be_a_heuristic_with_remediation() -> None:
    finding = Finding(**_FINDING, basis="heuristic", remediation="Rename the page.")
    assert finding.basis == "heuristic" and finding.remediation == "Rename the page."
    with pytest.raises(ValidationError):
        Finding(**_FINDING, basis="guess")
