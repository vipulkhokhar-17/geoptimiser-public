"""Categories D, F and J: content structure, extraction and retrieval-readiness heuristics."""

import bisect
from dataclasses import dataclass

from geoptimiser.features.checks._common import obs, types_of
from geoptimiser.features.context import Ctx, norm, terms
from geoptimiser.features.inputs import PageContext
from geoptimiser.features.outcome import (
    Outcome,
    failed,
    not_applicable,
    not_measured,
    passed,
)
from geoptimiser.features.registry import check
from geoptimiser.schemas import PageDocument

# --- D: content clarity ---------------------------------------------------------------


@check("F031")
def main_topic_clarity(page: PageContext, ctx: Ctx) -> Outcome:
    doc = page.document
    assert doc is not None
    h1s = [h for h in doc.headings if h.level == 1]
    if len(h1s) != 1 or not doc.title or not doc.title.strip():
        return not_applicable("Needs exactly one H1 and a title.")
    h1_terms = terms(h1s[0].text)
    if not h1_terms:
        return not_applicable("The H1 has no content terms.")
    pool = terms(doc.title) | terms(doc.text[:500])
    overlap = len(h1_terms & pool) / len(h1_terms)
    minimum = ctx.config.h1_overlap_min
    if overlap >= minimum:
        return passed(
            f"{overlap:.0%} of H1 terms appear in the title or opening text.",
            round(overlap, 3),
            f">= {minimum}",
        )
    return failed(
        f"Only {overlap:.0%} of H1 terms appear in the title or opening text.",
        (obs(page, f'title: "{doc.title}"; H1: "{h1s[0].text}"'),),
        round(overlap, 3),
        f">= {minimum}",
    )


@check("F035", version=2)
def heading_hierarchy(page: PageContext, ctx: Ctx) -> Outcome:
    doc = page.document
    assert doc is not None
    problems: list[str] = []
    h1_count = sum(1 for h in doc.headings if h.level == 1)
    cut = doc.source_truncated or "headings" in doc.truncated_fields
    if h1_count == 0 and not cut:  # in a cut document the H1 may lie beyond the cut
        problems.append("missing H1")
    elif h1_count > 1:
        problems.append(f"{h1_count} H1 elements")
    previous = 0
    for heading in doc.headings:
        if previous and heading.level > previous + 1:
            problems.append(f"h{previous} followed by h{heading.level}")
        if not heading.text.strip():
            problems.append(f"empty h{heading.level}")
        previous = heading.level
    if not problems:
        return passed("The heading outline is well-formed.", [], [])
    outline = ", ".join(f"h{h.level}" for h in doc.headings[:12]) or "no headings"
    return failed(
        "; ".join(problems).capitalize() + ".",
        (obs(page, f"outline: {outline}"),),
        problems,
        [],
    )


@check("F036")
def section_descriptiveness(page: PageContext, ctx: Ctx) -> Outcome:
    doc = page.document
    assert doc is not None
    if not doc.headings:
        return not_applicable("The page has no headings.")
    generic = {norm(g) for g in ctx.config.generic_headings}
    bad = [
        h.text
        for h in doc.headings
        if not any(c.isalpha() for c in h.text) or norm(h.text) in generic
    ]
    if not bad:
        return passed("No placeholder headings.", [], [])
    return failed(
        f"{len(bad)} placeholder or empty heading(s).",
        tuple(obs(page, f'heading: "{b}"') for b in bad[:5]),
        bad,
        [],
    )


@check("F040")
def question_answer_coverage(page: PageContext, ctx: Ctx) -> Outcome:
    from geoptimiser.features.checks._common import entities

    doc = page.document
    assert doc is not None
    questions = [h.text for h in doc.headings if h.text.strip().endswith("?")]
    qa_types = [
        t for e in entities(doc) for t in types_of(e) if t in ("FAQPage", "QAPage")
    ]
    observed = {
        "question_headings": len(questions),
        "qa_structured_data": len(qa_types),
    }
    if questions or qa_types:
        return passed("The page has a Q&A signal.", observed, ">= 1 signal")
    return failed(
        "No question headings or FAQ/QA structured data.",
        (obs(page, "0 question headings; no FAQPage/QAPage type"),),
        observed,
        ">= 1 signal",
    )


# --- F: extraction -------------------------------------------------------------------------


@check("F051")
def extractable_text(page: PageContext, ctx: Ctx) -> Outcome:
    doc = page.document
    assert doc is not None
    chars, words = len(doc.text), len(doc.text.split())
    minimum = ctx.config.min_extractable_chars
    observed = {"characters": chars, "words": words}
    if chars >= minimum:
        return passed(
            f"{chars} characters of extractable text.",
            observed,
            f">= {minimum} characters",
        )
    return failed(
        f"Only {chars} characters of extractable text (minimum {minimum}).",
        (obs(page, f"{chars} characters, {words} words extracted"),),
        observed,
        f">= {minimum} characters",
    )


@check("F060", requires="document")
def text_to_markup(page: PageContext, ctx: Ctx) -> Outcome:
    doc, body = page.document, page.fetch.body
    assert doc is not None
    if body is None or body.size_bytes == 0:
        return not_measured("No stored body to compare with.")
    if doc.source_truncated or body.truncated:
        return not_measured(
            "The stored body was truncated, so the ratio would be biased."
        )
    ratio = len(doc.text.encode("utf-8")) / body.size_bytes
    minimum = ctx.config.min_text_to_markup_ratio
    if ratio >= minimum:
        return passed(
            f"Text is {ratio:.1%} of the response.", round(ratio, 4), f">= {minimum}"
        )
    return failed(
        f"Text is only {ratio:.1%} of the response (minimum {minimum:.1%}).",
        (
            obs(
                page,
                f"{len(doc.text.encode())} text bytes of {body.size_bytes} HTML bytes",
            ),
        ),
        round(ratio, 4),
        f">= {minimum}",
    )


# --- J: retrieval readiness (heuristics on headings and text) -----------------------------


@dataclass(frozen=True)
class Section:
    heading: str | None
    chars: int
    text: str


def split_sections(doc: PageDocument) -> list[Section] | None:
    """Split the text at its heading lines (headings are their own text lines).

    Returns ``None`` if no heading can be located in the text, since the split
    would then be a guess.
    """
    lines = doc.text.split("\n")
    # Positions of each distinct line, so each heading is found by bisection instead of
    # rescanning the rest of the text; a heading that never matches no longer costs a
    # full scan (headings x lines, security audit run 1, hardening). Same result.
    positions: dict[str, list[int]] = {}
    for index, line in enumerate(lines):
        positions.setdefault(line, []).append(index)
    marks: list[tuple[int, str]] = []
    cursor = 0
    for heading in doc.headings:
        wanted = " ".join(heading.text.split())
        if not wanted:
            continue
        found = positions.get(wanted, ())
        at = bisect.bisect_left(found, cursor)
        if at < len(found):
            marks.append((found[at], wanted))
            cursor = found[at] + 1
    if not marks:
        return None
    sections: list[Section] = []
    if marks[0][0] > 0:
        body = "\n".join(lines[: marks[0][0]])
        sections.append(Section(None, len(body), body))
    for position, (index, heading) in enumerate(marks):
        end = marks[position + 1][0] if position + 1 < len(marks) else len(lines)
        body = "\n".join(lines[index + 1 : end])
        sections.append(Section(heading, len(body), body))
    return sections


@check("F091")
def chunkable_sections(page: PageContext, ctx: Ctx) -> Outcome:
    doc = page.document
    assert doc is not None
    if not doc.text.strip():
        return not_applicable("The page has no text.")
    sections = split_sections(doc)
    if sections is None:
        return not_measured(
            "No heading could be located in the text, so sections are unknown."
        )
    longest = max(sections, key=lambda s: s.chars)
    limit = ctx.config.max_section_chars
    observed = {"sections": len(sections), "longest_chars": longest.chars}
    if longest.chars <= limit:
        return passed(
            f"{len(sections)} sections; the longest has {longest.chars} characters.",
            observed,
            f"<= {limit}",
        )
    label = longest.heading or "(text before the first heading)"
    return failed(
        f'The section "{label}" has {longest.chars} characters (configured limit {limit}).',
        (obs(page, f'section "{label}": {longest.chars} characters'),),
        observed,
        f"<= {limit}",
    )


@check("F092")
def self_containment(page: PageContext, ctx: Ctx) -> Outcome:
    doc = page.document
    assert doc is not None
    sections = [s for s in (split_sections(doc) or []) if s.heading and s.text.strip()]
    if len(sections) < 2:
        return not_applicable("Needs at least two sections with text.")
    openers = tuple(norm(o) for o in ctx.config.dangling_openers)
    flagged: list[str] = []
    for section in sections:
        first = norm(section.text.split("\n", 1)[0])
        if any(first == o or first.startswith(o + " ") for o in openers):
            flagged.append(section.heading or "")
    if not flagged:
        return passed("No section opens with a dangling reference word.", [], [])
    return failed(
        f"{len(flagged)} section(s) open with a reference to earlier text.",
        tuple(
            obs(page, f'section "{h}" opens with a dangling reference')
            for h in flagged[:5]
        ),
        flagged,
        [],
    )
