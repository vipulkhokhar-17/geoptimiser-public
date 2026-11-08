"""Incomplete evidence is never a pass and never a confirmed failure (A1, A2, A5)."""

from geoptimiser.features.checks import _common  # noqa: F401  (registers checks)
from geoptimiser.features.config import FeatureConfig
from geoptimiser.features.evidence import (
    INTERSTITIAL_GUARDED,
    POLICIES,
    SELF_MANAGED,
    client_rendered_evidence,
    interstitial_marker,
)
from geoptimiser.features.registry import CHECKS, default_registry
from geoptimiser.schemas import RenderSignals
from tests.features.builders import audit, page, run, status_of

HOME = "https://www.example.com/"
A = "https://www.example.com/a"

CUT_BODY = {
    "ref": "sha256:" + "a" * 64,
    "sha256": "a" * 64,
    "size_bytes": 2_000_000,
    "truncated": True,
}


def cut_page(url: str = HOME, **doc: object):  # type: ignore[no-untyped-def]
    fields = {"source_truncated": True, "head_complete": False} | doc
    return page(url, fetch={"body": CUT_BODY}, doc=fields)


# --- the policy table is complete and honest ------------------------------------------


def test_every_document_check_declares_what_incomplete_evidence_can_prove() -> None:
    """A new content check cannot silently ignore truncation."""
    undeclared = []
    for fid, chk in sorted(CHECKS.items()):
        reads_document = chk.scope == "page" and chk.requires in (
            "document",
            "rich_document",
        )
        if reads_document and fid not in POLICIES and fid not in SELF_MANAGED:
            undeclared.append(fid)
    assert not undeclared, (
        f"declare an evidence policy (features/evidence.py) for {undeclared}"
    )


def test_policies_only_name_registered_checks() -> None:
    registry = default_registry()
    assert set(POLICIES) | set(SELF_MANAGED) <= set(registry.checks)
    assert not set(POLICIES) & set(SELF_MANAGED)
    assert INTERSTITIAL_GUARDED >= set(POLICIES)


# --- head vs body (A1) ----------------------------------------------------------------


def test_missing_title_is_not_concluded_when_the_head_was_cut() -> None:
    result = run("F021", audit(cut_page(title=None)))[0]
    assert result.status == "not_measured"
    assert "truncated at 2,000,000 bytes" in (result.explanation or "")


def test_missing_title_is_a_failure_once_the_head_was_read() -> None:
    p = cut_page(title=None, head_complete=True)
    assert status_of("F021", p) == "fail"
    assert status_of("F024", cut_page(meta_description=None, head_complete=True)) == (
        "fail"
    )


def test_a_title_that_was_read_is_valid_even_if_the_body_was_cut() -> None:
    assert status_of("F021", cut_page(title="Real title")) == "pass"


def test_unknown_head_state_from_an_older_extractor_is_treated_as_unknown() -> None:
    assert status_of("F021", cut_page(title=None, head_complete=None)) == (
        "not_measured"
    )


def test_a_complete_document_is_unaffected() -> None:
    assert status_of("F021", page(HOME, doc={"title": None})) == "fail"


def test_noindex_that_was_seen_counts_but_no_noindex_needs_the_whole_head() -> None:
    seen = cut_page(meta_robots="noindex")
    assert status_of("F005", seen) == "warning"
    assert status_of("F005", cut_page(meta_robots=None)) == "not_measured"
    assert status_of("F005", cut_page(meta_robots=None, head_complete=True)) == "pass"


def test_presence_in_the_body_is_kept_but_its_absence_is_not_concluded() -> None:
    long_text = "Real extracted body text. " * 20
    assert status_of("F051", cut_page(text=long_text)) == "pass"
    assert status_of("F051", cut_page(text="")) == "not_measured"


def test_ratios_and_totals_need_the_whole_document() -> None:
    assert status_of("F014", cut_page(text="Identical text. " * 30)) == "not_measured"
    assert status_of("F060", cut_page()) == "not_measured"


def test_a_violation_that_was_seen_is_kept_but_a_clean_prefix_is_not_a_pass() -> None:
    bad = cut_page(
        headings=[{"level": 1, "text": "Section"}, {"level": 5, "text": "x"}]
    )
    assert status_of("F035", bad) == "fail"
    good = cut_page(headings=[{"level": 1, "text": "Section"}])
    assert status_of("F035", good) == "not_measured"
    # "no H1" in a cut document may just mean the H1 comes later.
    assert status_of("F035", cut_page(headings=[])) == "not_measured"


def test_extraction_limits_are_incomplete_evidence_too() -> None:
    capped = page(HOME, doc={"truncated_fields": ["text"], "text": ""})
    assert status_of("F051", capped) == "not_measured"
    # ...but only for the field that was capped.
    assert status_of("F021", page(HOME, doc={"truncated_fields": ["text"]})) == "pass"


def test_truncated_title_value_is_not_judged() -> None:
    cut_title = page(HOME, doc={"title": "Home", "truncated_fields": ["title"]})
    assert status_of("F023", cut_title) == "not_measured"  # generic-looking, but cut
    assert status_of("F021", cut_title) == "pass"  # a title does exist


# --- JSON-LD causes (A5) --------------------------------------------------------------


def f61(**doc: object) -> tuple[str, str]:
    r = run("F061", audit(page(HOME, doc=doc)))[0]
    return r.status, r.explanation or ""


def test_complete_but_invalid_json_ld_is_a_failure() -> None:
    status, why = f61(
        structured_data_errors=1, structured_data_error_causes={"syntax_error": 1}
    )
    assert status == "fail" and "could not be parsed" in why


def test_a_block_cut_by_truncation_is_not_a_syntax_error() -> None:
    p = cut_page(
        structured_data_errors=1, structured_data_error_causes={"unterminated": 1}
    )
    r = run("F061", audit(p))[0]
    assert r.status == "not_measured"
    assert "truncated" in (r.explanation or "") and "syntax" not in r.explanation


def test_an_unclosed_block_in_a_complete_document_is_a_real_defect() -> None:
    status, _ = f61(
        structured_data_errors=1, structured_data_error_causes={"unterminated": 1}
    )
    assert status == "fail"


def test_a_block_skipped_for_size_is_not_a_failure() -> None:
    for cause in ("size_limit", "nesting_limit"):
        status, why = f61(
            structured_data_errors=1,
            structured_data_error_causes={cause: 1},
            truncated_fields=["structured_data"],
        )
        assert status == "not_measured" and "limit" in why


def test_old_documents_without_causes_stay_a_failure_unless_truncated() -> None:
    assert f61(structured_data_errors=2)[0] == "fail"
    p = cut_page(structured_data_errors=2)
    assert run("F061", audit(p))[0].status == "not_measured"


def test_no_json_ld_is_not_applicable_only_in_a_complete_document() -> None:
    assert f61()[0] == "not_applicable"
    assert run("F061", audit(cut_page()))[0].status == "not_measured"


def test_valid_json_ld_passes_and_a_cut_document_cannot_vouch_for_the_rest() -> None:
    assert f61(structured_data=[{"@type": "Organization", "name": "x"}])[0] == "pass"
    cut = cut_page(structured_data=[{"@type": "Organization", "name": "x"}])
    assert run("F061", audit(cut))[0].status == "not_measured"


def test_a_syntax_error_in_a_cut_document_is_still_a_failure() -> None:
    p = cut_page(
        structured_data_errors=2,
        structured_data_error_causes={"syntax_error": 1, "unterminated": 1},
    )
    r = run("F061", audit(p))[0]
    assert r.status == "fail" and "cut by the truncated response" in (
        r.explanation or ""
    )


# --- response states (B1) -------------------------------------------------------------


def test_interstitial_pages_are_recognised_and_content_checks_stand_down() -> None:
    p = page(HOME, doc={"title": "Just a moment...", "text": "Checking your browser."})
    assert (
        interstitial_marker(
            p.document,
            __import__("geoptimiser.features.config", fromlist=["x"]).FeatureConfig(),
        )
        == "just a moment"
    )  # type: ignore[arg-type]
    r = run("F024", audit(p))[0]
    assert r.status == "not_measured" and "interstitial" in (r.explanation or "")


def test_a_long_page_mentioning_captcha_is_not_an_interstitial() -> None:
    p = page(HOME, doc={"title": "Spam protection guide", "text": "captcha " * 600})
    assert interstitial_marker(p.document, FeatureConfig()) is None  # type: ignore[arg-type]


def test_client_rendered_shell_needs_little_text_and_a_concrete_sign() -> None:
    cfg = FeatureConfig()
    shell = page(
        HOME,
        doc={
            "text": "",
            "render_signals": RenderSignals(script_tags=3, mount_points=("#root",)),
        },
    ).document
    assert "#root" in (client_rendered_evidence(shell, cfg) or "")  # type: ignore[arg-type]
    plain = page(HOME, doc={"text": "", "render_signals": RenderSignals()}).document
    assert client_rendered_evidence(plain, cfg) is None  # type: ignore[arg-type]
    wordy = page(
        HOME,
        doc={
            "text": "word " * 200,
            "render_signals": RenderSignals(script_tags=5, mount_points=("#root",)),
        },
    ).document
    assert client_rendered_evidence(wordy, cfg) is None  # type: ignore[arg-type]


def test_a_failure_on_a_client_rendered_page_says_so_without_changing_status() -> None:
    p = page(
        HOME,
        doc={
            "title": None,
            "text": "",
            "render_signals": RenderSignals(script_tags=3, mount_points=("#root",)),
        },
    )
    r = run("F021", audit(p))[0]
    assert r.status == "fail"
    assert any("does not execute JavaScript" in x for x in r.limitations)


# --- evidence about other pages (A2) --------------------------------------------------


def test_orphan_is_not_concluded_while_another_pages_links_are_unknown() -> None:
    home = page(HOME, doc={"links": []})
    leaf = page(A, doc={"links": []})
    results = {r.subject_url: r.status for r in run("F009", audit(home, leaf))}
    assert results[A] == "fail"  # every link list is known: really nobody links to A
    cut_home = cut_page(HOME, links=[])
    results = {r.subject_url: r.status for r in run("F009", audit(cut_home, leaf))}
    assert results[A] == "not_measured"
    # the same for the click-depth and incoming-link checks
    assert {
        r.status for r in run("F072", audit(cut_home, leaf)) if r.subject_url == A
    } == {"not_measured"}


def test_f009_and_f072_agree_on_every_page_at_default_thresholds() -> None:
    inputs = audit(
        page(HOME, doc={"links": [A]}),
        page(A, doc={"links": []}),
        page("https://www.example.com/b", doc={"links": []}),
    )
    f9 = {r.subject_url: r.status for r in run("F009", inputs)}
    f72 = {r.subject_url: r.status for r in run("F072", inputs, min_incoming_links=1)}
    assert f9 == f72  # exact duplicates: counting both would double the same fact
    # With a minimum of 0 F072 can never fail, so it is not a duplicate but a free pass.
    f72_zero = {r.status for r in run("F072", inputs, min_incoming_links=0)}
    assert f72_zero <= {"pass", "not_applicable"}


def test_f072_differs_from_f009_once_the_minimum_is_raised() -> None:
    inputs = audit(page(HOME, doc={"links": [A]}), page(A, doc={"links": []}))
    assert {r.status for r in run("F009", inputs) if r.subject_url == A} == {"pass"}
    assert {
        r.status
        for r in run("F072", inputs, min_incoming_links=2)
        if r.subject_url == A
    } == {"fail"}
