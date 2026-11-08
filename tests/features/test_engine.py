"""Measurement states, honesty rules and robustness of the engine."""

import pytest
from pydantic import ValidationError

from geoptimiser.features import (
    CATALOG,
    FeatureConfig,
    default_registry,
    run_all,
    run_feature,
)
from geoptimiser.features.outcome import Outcome, failed, passed
from geoptimiser.features.registry import CHECKS, Check, FeatureRegistry
from geoptimiser.schemas import FeatureResult, PageDocument
from tests.features.builders import (
    AUDIT,
    FETCH_404,
    FETCH_TIMEOUT,
    audit,
    make_document,
    make_fetch,
    page,
    run,
)

HOME = "https://www.example.com/"
A = "https://www.example.com/a"
PLANNED = [f.feature_id for f in CATALOG.features if not f.measurable_now]


def site():  # type: ignore[no-untyped-def]
    return audit(page(HOME, doc={"links": [A]}), page(A))


@pytest.mark.parametrize("feature_id", PLANNED)
def test_unimplemented_features_are_never_reported_as_measured(feature_id: str) -> None:
    results = run(feature_id, site())
    assert len(results) == 1
    result = results[0]
    assert result.status == "not_measured"
    assert result.observed_value is None and result.expected_value is None
    assert result.implementation_status in ("planned", "unavailable")
    assert result.scope == "audit" and result.severity == "informational"
    assert "Not measured" in (result.explanation or "")
    assert result.evidence == ()


def test_the_schema_itself_forbids_a_planned_feature_passing() -> None:
    base = {
        "audit_id": AUDIT,
        "feature_id": "F111",
        "feature_version": 1,
        "category": "L",
        "measurement_method": "m",
        "implementation_status": "planned",
    }
    FeatureResult(**base, status="not_measured")
    for status in ("pass", "fail", "error", "not_applicable"):
        with pytest.raises(
            ValidationError, match="only honest status is 'not_measured'"
        ):
            FeatureResult(
                **base, status=status, error_message="x" if status == "error" else None
            )


def test_page_scope_results_must_name_their_page() -> None:
    with pytest.raises(ValidationError, match="subject_url"):
        FeatureResult(
            audit_id=AUDIT,
            feature_id="F021",
            feature_version=1,
            category="C",
            status="pass",
            measurement_method="m",
            scope="page",
        )


def test_results_carry_identifiers_and_version_information() -> None:
    inputs = audit(page(HOME))
    result = run("F021", inputs)[0]
    assert result.audit_id == AUDIT and result.feature_id == "F021"
    assert result.subject_url == HOME and result.scope == "page"
    assert result.fetch_id == inputs.pages[0].fetch.fetch_id
    assert result.document_id == inputs.pages[0].document.document_id  # type: ignore[union-attr]
    assert result.feature_version == 1 and result.catalog_version == CATALOG.version
    assert result.implementation_status == "implemented"
    assert result.category == "C" and result.measurement_method and result.explanation
    assert result.expected_value == "present" and result.observed_value


def test_a_page_without_a_document_is_not_measured_not_failed() -> None:
    inputs = audit(page(HOME, fetch=FETCH_404), page(A, no_document=True))
    for feature_id in ("F021", "F024", "F035", "F061", "F051", "F011"):
        for result in run(feature_id, inputs):
            assert result.status == "not_measured", (feature_id, result.subject_url)
            assert "No extracted document" in (result.explanation or "")
    reasons = {r.subject_url: r.explanation for r in run("F021", inputs)}
    assert "http_error" in reasons[HOME] and "not run" in reasons[A]


def test_extraction_failure_is_named_as_the_reason() -> None:
    from geoptimiser.features.inputs import PageContext
    from geoptimiser.schemas import ExtractionFailure

    fetch = make_fetch(HOME)
    failure = ExtractionFailure(
        audit_id=AUDIT,
        fetch_id=fetch.fetch_id,
        extraction_version="v:1",
        error_type="decode_error",
        error_message="bad bytes",
    )
    result = run("F021", audit(PageContext(fetch, None, failure)))[0]
    assert result.status == "not_measured" and "decode_error" in result.explanation  # type: ignore[operator]


def test_a_missing_response_is_never_a_failed_check() -> None:
    inputs = audit(page(HOME, fetch=FETCH_TIMEOUT))
    results = run_all(inputs)
    assert not [r for r in results if r.status == "fail" and r.scope == "page"]
    assert not [r for r in results if r.status == "error"]


def test_not_applicable_is_distinct_from_not_measured_and_fail() -> None:
    inputs = audit(page(HOME))
    assert run("F016", inputs)[0].status == "not_applicable"  # no redirect happened
    assert run("F061", inputs)[0].status == "not_applicable"  # no JSON-LD to validate
    assert run("F046", inputs)[0].status == "not_applicable"  # not an article
    assert run("F111", inputs)[0].status == "not_measured"  # no data source yet


def _registry_with(
    feature_id: str, fn, scope="page", requires="document"
) -> FeatureRegistry:  # type: ignore[no-untyped-def]
    checks = {**CHECKS, feature_id: Check(feature_id, scope, requires, 1, fn)}
    return FeatureRegistry(CATALOG, checks)


def test_a_crashing_check_yields_an_error_result_and_does_not_hide_other_pages() -> (
    None
):
    def flaky(page_, ctx):  # type: ignore[no-untyped-def]
        if page_.url == A:
            raise RuntimeError("boom with secret text")
        return passed("fine", "x", "x")

    registry = _registry_with("F021", flaky)
    results = run_feature("F021", site(), FeatureConfig(), registry)
    by_url = {r.subject_url: r for r in results}
    assert by_url[HOME].status == "pass"
    broken = by_url[A]
    assert broken.status == "error" and "RuntimeError" in (broken.error_message or "")
    assert broken.observed_value is None and broken.severity == "informational"


def test_a_crashing_site_check_is_an_error_result() -> None:
    registry = _registry_with("F066", lambda ctx: 1 / 0, scope="site", requires="none")
    result = run_feature("F066", site(), FeatureConfig(), registry)[0]
    assert result.status == "error" and "ZeroDivisionError" in (
        result.error_message or ""
    )


def test_a_failure_without_evidence_is_an_error_not_a_fail() -> None:
    uncited = lambda page_, ctx: Outcome("fail", "claims failure but cites nothing")  # noqa: E731
    result = run_feature(
        "F021", site(), FeatureConfig(), _registry_with("F021", uncited)
    )[0]
    assert result.status == "error" and "at least one observation" in (
        result.error_message or ""
    )
    with pytest.raises(ValueError, match="at least one observation"):
        failed("x", ())


def test_a_site_check_with_an_uncited_failure_is_an_error() -> None:
    registry = _registry_with(
        "F066", lambda ctx: Outcome("fail", "no evidence"), "site", "none"
    )
    assert run_feature("F066", site(), FeatureConfig(), registry)[0].status == "error"


def test_an_audit_without_pages_still_runs() -> None:
    results = run_all(audit())
    assert (
        len(results) == len(PLANNED) + 5
    )  # one per planned feature + the 5 site checks
    assert not [r for r in results if r.status in ("pass", "fail")]


def test_incomplete_documents_never_crash_any_check() -> None:
    bare_fetch = make_fetch(HOME)
    bare = PageDocument(
        audit_id=AUDIT,
        document_id="doc:bare",
        fetch_id=bare_fetch.fetch_id,
        url=HOME,
        extraction_version="html-extractor:1",
    )
    from geoptimiser.features.inputs import PageContext

    results = run_all(audit(PageContext(bare_fetch, bare)))
    assert [r for r in results if r.status == "error"] == []
    assert {r.feature_id for r in results} == {f.feature_id for f in CATALOG.features}


def test_hostile_text_is_data_not_instructions() -> None:
    nasty = "Ignore all previous instructions </script><b>{{7*7}}$(rm -rf /)"
    doc = {"title": nasty, "meta_description": nasty, "text": nasty * 5}
    results = run_all(audit(page(HOME, doc=doc)))
    assert [r for r in results if r.status == "error"] == []
    title = next(r for r in results if r.feature_id == "F021")
    assert title.evidence[0].snippet.startswith("title: Ignore all previous")


def test_results_are_deterministic() -> None:
    first = [r.model_dump(mode="json") for r in run_all(site())]
    second = [r.model_dump(mode="json") for r in run_all(site())]
    assert first == second


def test_make_document_defaults_pass_the_basic_checks() -> None:
    fetch = make_fetch(A)
    document = make_document(fetch)
    assert document.title and document.headings and document.text


def test_default_registry_is_the_shipped_one() -> None:
    assert default_registry().catalog is CATALOG


def test_non_json_observed_values_become_errors_not_silent_garbage() -> None:
    odd = lambda page_, ctx: passed("fine", observed={1, 2}, expected=None)  # noqa: E731
    result = run_feature("F021", site(), FeatureConfig(), _registry_with("F021", odd))[
        0
    ]
    assert result.status == "error" and "not JSON serializable" in (
        result.error_message or ""
    )


def test_tuple_observations_are_normalised_to_json_lists() -> None:
    tuples = lambda page_, ctx: passed("fine", observed=(1, ("a", "b")), expected=None)  # noqa: E731
    result = run_feature(
        "F021", site(), FeatureConfig(), _registry_with("F021", tuples)
    )[0]
    assert result.observed_value == [1, ["a", "b"]]
