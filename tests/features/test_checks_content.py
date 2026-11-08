"""Categories C, D, F and J."""

import pytest

from geoptimiser.schemas import Heading
from tests.features.builders import (
    FETCH_TIMEOUT,
    audit,
    page,
    run,
    status_of,
    statuses,
)

HOME = "https://www.example.com/"
A = "https://www.example.com/a"
B = "https://www.example.com/b"


# --- C: metadata --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Pricing plans for teams", "pass"),
        (None, "fail"),
        ("", "fail"),
        ("  \n ", "fail"),
    ],
)
def test_f021_title_presence(title: str | None, expected: str) -> None:
    assert status_of("F021", page(HOME, doc={"title": title})) == expected


def test_f021_failure_evidence_states_the_absence() -> None:
    result = run("F021", audit(page(HOME, doc={"title": None})))[0]
    assert (
        result.evidence[0].source_url == HOME
        and "no title" in result.evidence[0].snippet
    )
    assert result.observed_value is None and result.severity == "high"


def test_f022_title_uniqueness_across_pages() -> None:
    inputs = audit(
        page(HOME, doc={"title": "Pricing Plans"}),
        page(A, doc={"title": "  pricing   plans "}),
        page(B, doc={"title": "About us"}),
        page("https://www.example.com/c", doc={"title": None}),
    )
    result = statuses("F022", inputs)
    assert result[HOME] == "fail" and result[A] == "fail"
    assert result[B] == "pass"
    assert result["https://www.example.com/c"] == "not_applicable"
    failing = next(r for r in run("F022", inputs) if r.subject_url == HOME)
    assert {e.source_url for e in failing.evidence} == {HOME, A}


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Home", "fail"),
        ("UNTITLED", "fail"),
        ("12345", "fail"),
        ("Pricing plans", "pass"),
    ],
)
def test_f023_title_descriptiveness(title: str, expected: str) -> None:
    assert status_of("F023", page(HOME, doc={"title": title})) == expected
    assert status_of("F023", page(HOME, doc={"title": None})) == "not_applicable"


def test_f023_generic_list_is_configuration() -> None:
    custom = {"generic_titles": ("pricing plans",)}
    assert (
        status_of("F023", page(HOME, doc={"title": "Pricing plans"}), **custom)
        == "fail"
    )


def test_f024_and_f025_descriptions() -> None:
    assert (
        status_of("F024", page(HOME, doc={"meta_description": "A summary"})) == "pass"
    )
    assert status_of("F024", page(HOME, doc={"meta_description": None})) == "fail"
    assert status_of("F024", page(HOME, doc={"meta_description": ""})) == "fail"
    inputs = audit(
        page(HOME, doc={"meta_description": "Same text"}),
        page(A, doc={"meta_description": "same   text"}),
        page(B, doc={"meta_description": "Different"}),
    )
    unique = statuses("F025", inputs)
    assert (unique[HOME], unique[A], unique[B]) == ("fail", "fail", "pass")


def test_f026_description_content_alignment_is_a_heuristic() -> None:
    text = "Our pricing plans include a free tier and paid team subscriptions."
    aligned = page(
        HOME,
        doc={
            "meta_description": "Pricing plans, free tier, team subscriptions",
            "text": text,
        },
    )
    off_topic = page(
        HOME,
        doc={
            "meta_description": "Quantum computing breakthroughs galore",
            "text": text,
        },
    )
    assert run("F026", audit(aligned))[0].status == "pass"
    result = run("F026", audit(off_topic))[0]
    assert result.status == "fail" and result.is_heuristic
    assert result.expected_value == ">= 0.5"
    assert (
        status_of("F026", page(HOME, doc={"meta_description": None}))
        == "not_applicable"
    )
    assert (
        status_of(
            "F026", page(HOME, doc={"meta_description": "The and of", "text": text})
        )
        == "not_applicable"
    )
    assert status_of("F026", page(HOME, doc={"text": ""})) == "not_applicable"


@pytest.mark.parametrize(
    ("lang", "expected"),
    [
        ("en", "pass"),
        ("en-GB", "pass"),
        ("zh-Hant-TW", "pass"),
        (None, "fail"),
        ("", "fail"),
        ("english!", "fail"),
    ],
)
def test_f027_language(lang: str | None, expected: str) -> None:
    assert status_of("F027", page(HOME, doc={"language": lang})) == expected


def test_f028_charset_declaration() -> None:
    declared = {"headers": {"Content-Type": "text/html; charset=utf-8"}}
    assert status_of("F028", page(HOME, fetch=declared)) == "pass"
    bare = {"headers": {"Content-Type": "text/html"}}
    assert (
        status_of("F028", page(HOME, fetch=bare)) == "fail"
    )  # level-2 document: no meta
    meta = page(HOME, fetch=bare, doc={"charset_declared": "utf-8"})
    assert run("F028", audit(meta))[0].status == "pass"
    old = page(HOME, fetch=bare, doc={"detail_level": 1})
    assert run("F028", audit(old))[0].status == "not_measured"  # meta charset unknown
    assert status_of("F028", page(HOME, fetch=FETCH_TIMEOUT)) == "not_measured"


@pytest.mark.parametrize(
    ("meta", "header", "expected"),
    [
        (None, None, "pass"),
        ("nosnippet", None, "warning"),  # owner policy: confirm intent, not a defect
        ("max-snippet:0", None, "warning"),
        ("max-snippet:50", None, "pass"),
        ("max-snippet:-1", None, "pass"),
        (None, "nosnippet", "warning"),
        ("noarchive", None, "pass"),
    ],
)
def test_f030_snippet_restrictions(
    meta: str | None, header: str | None, expected: str
) -> None:
    headers = {"Content-Type": "text/html"} | (
        {"X-Robots-Tag": header} if header else {}
    )
    assert (
        status_of(
            "F030", page(HOME, doc={"meta_robots": meta}, fetch={"headers": headers})
        )
        == expected
    )


# --- D: content clarity ------------------------------------------------------------------------


def test_f031_main_topic_clarity() -> None:
    aligned = {
        "title": "Pricing plans for small teams",
        "headings": [Heading(level=1, text="Pricing plans")],
        "text": "Pricing plans\nOur plans suit small teams.",
    }
    assert status_of("F031", page(HOME, doc=aligned)) == "pass"
    mismatch = {
        **aligned,
        "title": "Contact our offices",
        "headings": [Heading(level=1, text="Quantum gravity lectures")],
        "text": "Welcome to the offices page.",
    }
    result = run("F031", audit(page(HOME, doc=mismatch)))[0]
    assert result.status == "fail" and result.is_heuristic
    two_h1 = {
        **aligned,
        "headings": [Heading(level=1, text="A"), Heading(level=1, text="B")],
    }
    assert status_of("F031", page(HOME, doc=two_h1)) == "not_applicable"
    assert (
        status_of("F031", page(HOME, doc={**aligned, "title": None}))
        == "not_applicable"
    )


@pytest.mark.parametrize(
    ("levels", "texts", "expected"),
    [
        ([1, 2, 3, 2], None, "pass"),
        ([1, 1], None, "fail"),
        ([2, 3], None, "fail"),
        ([1, 3], None, "fail"),
        ([], None, "fail"),
        ([1, 2], ["T", ""], "fail"),
        ([1, 2, 1, 2], None, "fail"),
        ([1, 2, 3, 1 + 1], None, "pass"),
    ],
)
def test_f035_heading_hierarchy(
    levels: list[int], texts: list[str] | None, expected: str
) -> None:
    headings = [
        Heading(level=lv, text=(texts[i] if texts else f"Heading {i}"))
        for i, lv in enumerate(levels)
    ]
    assert status_of("F035", page(HOME, doc={"headings": headings})) == expected


def test_f035_reports_each_violation() -> None:
    headings = [
        Heading(level=1, text="A"),
        Heading(level=1, text="B"),
        Heading(level=4, text="C"),
    ]
    result = run("F035", audit(page(HOME, doc={"headings": headings})))[0]
    assert result.status == "fail"
    assert any("2 H1" in p for p in result.observed_value)
    assert any("h1 followed by h4" in p for p in result.observed_value)


def test_f036_section_descriptiveness() -> None:
    ok = [Heading(level=1, text="Pricing"), Heading(level=2, text="Free tier")]
    assert status_of("F036", page(HOME, doc={"headings": ok})) == "pass"
    bad = [*ok, Heading(level=2, text="Read more"), Heading(level=2, text="***")]
    result = run("F036", audit(page(HOME, doc={"headings": bad})))[0]
    assert result.status == "fail" and result.observed_value == ["Read more", "***"]
    assert status_of("F036", page(HOME, doc={"headings": []})) == "not_applicable"


def test_f040_question_and_answer_signal() -> None:
    q = [Heading(level=2, text="What does it cost?")]
    assert status_of("F040", page(HOME, doc={"headings": q})) == "pass"
    faq = {"headings": [], "structured_data": [{"@type": "FAQPage", "mainEntity": []}]}
    assert status_of("F040", page(HOME, doc=faq)) == "pass"
    assert status_of("F040", page(HOME, doc={"headings": []})) == "fail"


# --- F: extraction ---------------------------------------------------------------------------------


def test_f051_extractable_text() -> None:
    assert status_of("F051", page(HOME, doc={"text": "x" * 150})) == "pass"
    shell = run("F051", audit(page(HOME, doc={"text": ""})))[0]
    assert shell.status == "fail" and shell.observed_value == {
        "characters": 0,
        "words": 0,
    }
    assert (
        status_of(
            "F051", page(HOME, doc={"text": "x" * 150}), min_extractable_chars=200
        )
        == "fail"
    )


def test_f060_text_to_markup_ratio() -> None:
    body = lambda size, **kw: {
        "body": {
            "ref": "sha256:" + "a" * 64,
            "sha256": "a" * 64,
            "size_bytes": size,
            **kw,
        }
    }  # noqa: E731
    text = {"text": "x" * 1000}
    assert status_of("F060", page(HOME, doc=text, fetch=body(10_000))) == "pass"
    assert status_of("F060", page(HOME, doc=text, fetch=body(1_000_000))) == "fail"
    truncated = run(
        "F060", audit(page(HOME, doc=text, fetch=body(10_000, truncated=True)))
    )[0]
    assert truncated.status == "not_measured"  # a cut body would bias the ratio


# --- J: retrieval readiness --------------------------------------------------------------------------

SECTIONED = {
    "headings": [
        Heading(level=1, text="Guide"),
        Heading(level=2, text="Setup"),
        Heading(level=2, text="Usage"),
    ],
    "text": "Guide\nIntro paragraph.\nSetup\nInstall the package first.\nUsage\nThis shows how to run it.",
}


def test_f091_chunkable_sections() -> None:
    result = run("F091", audit(page(HOME, doc=SECTIONED)))[0]
    assert result.status == "pass" and result.observed_value["sections"] == 3
    assert status_of("F091", page(HOME, doc=SECTIONED), max_section_chars=10) == "fail"
    assert (
        status_of("F091", page(HOME, doc={"headings": [], "text": "Plain text only."}))
        == "not_measured"
    )
    assert (
        status_of("F091", page(HOME, doc={"headings": [], "text": ""}))
        == "not_applicable"
    )


def test_f091_long_unsplit_text_fails_and_names_the_section() -> None:
    doc = {
        "headings": [Heading(level=1, text="Wall")],
        "text": "Wall\n" + "word " * 2000,
    }
    result = run("F091", audit(page(HOME, doc=doc)))[0]
    assert (
        result.status == "fail" and "Wall" in result.explanation and result.is_heuristic
    )


def test_f092_section_self_containment() -> None:
    assert (
        status_of("F092", page(HOME, doc=SECTIONED)) == "fail"
    )  # "Usage" opens with "This"
    fine = {
        **SECTIONED,
        "text": SECTIONED["text"].replace("This shows", "Running the tool shows"),
    }
    assert status_of("F092", page(HOME, doc=fine)) == "pass"
    one = {"headings": [Heading(level=1, text="Only")], "text": "Only\nSome text."}
    assert status_of("F092", page(HOME, doc=one)) == "not_applicable"


def test_split_sections_is_not_headings_times_lines() -> None:
    # Security audit run 1 (hardening): an unmatched heading used to rescan every
    # remaining line, so many unmatched headings cost headings x lines.
    import time

    from geoptimiser.features.checks.content import split_sections
    from tests.features.builders import make_document, make_fetch

    lines = [f"line {i}" for i in range(100_000)]
    headings = [Heading(level=2, text=f"missing {i}") for i in range(2_000)]
    headings.insert(1000, Heading(level=2, text="line 50000"))
    doc = make_document(make_fetch(HOME), text="\n".join(lines), headings=headings)
    start = time.perf_counter()
    sections = split_sections(doc)
    assert time.perf_counter() - start < 1.0
    assert sections is not None and [s.heading for s in sections] == [
        None,
        "line 50000",
    ]


def test_split_sections_keeps_document_order_for_repeated_lines() -> None:
    from geoptimiser.features.checks.content import split_sections
    from tests.features.builders import make_document, make_fetch

    text = "intro\nA\nx\nB\ny\nA\nz"
    heads = [Heading(level=2, text=t) for t in ("A", "B", "A")]
    doc = make_document(make_fetch(HOME), text=text, headings=heads)
    got = [(s.heading, s.chars) for s in split_sections(doc) or []]
    assert got == [(None, 5), ("A", 1), ("B", 1), ("A", 1)]
