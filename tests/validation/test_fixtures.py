"""Every synthetic fixture runs through the real pipeline and meets its expectations.

The expectations in each ``spec.json`` were written from the validation policy before
the implementation was changed to meet them (docs/validation/VALIDATION_METHODOLOGY.md).
A failure here means a regression in measurement semantics, not a flaky test: the
fixtures are served from memory and never touch the network.
"""

from pathlib import Path

import pytest

from geoptimiser.validation import evaluate_fixture, load_fixtures, run_fixture
from geoptimiser.validation.spec import FixtureSpec

FIXTURES = Path(__file__).parent / "fixtures"
SPECS = load_fixtures(FIXTURES)


def test_fixtures_exist_and_cover_the_required_scenarios() -> None:
    ids = {s.id for s in SPECS}
    required = {
        "clean_static",  # a clean static page
        "a1_trunc_before_title",  # truncation before a title
        "a1_trunc_after_title",  # truncation after a valid title
        "a1_trunc_jsonld",  # truncated JSON-LD
        "a1_complete_missing_metadata",  # genuinely missing metadata, complete page
        "yt_like_js_heavy",  # JavaScript-heavy initial HTML
        "b1_hydration_hidden",  # hydration-dependent content
        "a2_canonical_states",  # valid/invalid canonical, unavailable target
        "a5_jsonld_states",  # valid, invalid, missing JSON-LD
        "a5_jsonld_size_limit",  # skipped for size
        "b4_ai_crawler_blocked",  # intentional crawler directives
        "b4_noindex_intentional",  # legitimate noindex
        "b2_link_forms",  # ordinary links, <noscript>, malformed HTML
        "b1_empty_blocked_nonhtml",  # empty or blocked response
        "combined_realistic_mix",  # duplicate and independent failures together
        "a3_single_root_cause",
        "a3_independent_failures",
        "empty_failed_crawl",
        "crawl_incomplete_max_pages",
    }
    assert required <= ids


def test_fixture_ids_are_unique_and_match_their_directories() -> None:
    assert len({s.id for s in SPECS}) == len(SPECS)
    assert all(s.directory is not None and s.directory.name == s.id for s in SPECS)


def test_every_fixture_declares_expectations() -> None:
    for spec in SPECS:
        e = spec.expect
        assert (
            e.pages
            or e.site
            or e.findings.present
            or e.findings.absent
            or e.scores.overall
        ), spec.id


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.id)
def test_fixture_meets_its_expectations(spec: FixtureSpec, tmp_path: Path) -> None:
    evaluation = evaluate_fixture(run_fixture(spec, tmp_path))
    assert evaluation.results, "a fixture with no checked expectation proves nothing"
    failures = [
        f"{r.kind} {r.subject}: expected {r.expected}, got {r.actual} ({r.detail})"
        for r in evaluation.failures
    ]
    assert not failures, "\n".join(failures)
