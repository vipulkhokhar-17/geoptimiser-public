"""Category C: metadata and search-result presentation."""

import re

from geoptimiser.features.checks._common import (
    intent_severity,
    obs,
    robots_directives,
)
from geoptimiser.features.context import Ctx, norm, terms
from geoptimiser.features.inputs import PageContext
from geoptimiser.features.outcome import (
    Outcome,
    failed,
    not_applicable,
    not_measured,
    passed,
    warned,
)
from geoptimiser.features.registry import check

_LANG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")


def _presence(page: PageContext, label: str, value: str | None) -> Outcome:
    if value is None:
        return failed(
            f"No {label} was found.", (obs(page, f"no {label}"),), None, "present"
        )
    if not value.strip():
        return failed(
            f"The {label} is blank.", (obs(page, f"{label} is blank"),), "", "present"
        )
    return passed(
        f"A {label} is present.", value, "present", (obs(page, f"{label}: {value}"),)
    )


def _uniqueness(page: PageContext, value: str | None, index, label: str) -> Outcome:  # type: ignore[no-untyped-def]
    if value is None or not value.strip():
        return not_applicable(f"The page has no {label} to compare.")
    others = [p for p in index.get(norm(value), []) if p.key != page.key]
    if not others:
        return passed(f"The {label} is unique among crawled pages.", [], [])
    return failed(
        f"{len(others)} other page(s) share this {label}.",
        (
            obs(page, f'{label}: "{value}"'),
            *[obs(o, f'same {label}: "{value}"') for o in others[:5]],
        ),
        [o.url for o in others],
        [],
    )


@check("F021")
def title_presence(page: PageContext, ctx: Ctx) -> Outcome:
    assert page.document is not None
    return _presence(page, "title", page.document.title)


@check("F022")
def title_uniqueness(page: PageContext, ctx: Ctx) -> Outcome:
    assert page.document is not None
    return _uniqueness(page, page.document.title, ctx.title_index, "title")


@check("F023")
def title_descriptiveness(page: PageContext, ctx: Ctx) -> Outcome:
    assert page.document is not None
    title = page.document.title
    if not title or not title.strip():
        return not_applicable("The page has no title to judge.")
    generic = norm(title) in {norm(t) for t in ctx.config.generic_titles}
    if generic or not any(c.isalpha() for c in title):
        return failed(
            "The title is a generic placeholder.",
            (obs(page, f'title: "{title}"'),),
            title,
            "not generic",
        )
    return passed("The title is not a generic placeholder.", title, "not generic")


@check("F024")
def description_presence(page: PageContext, ctx: Ctx) -> Outcome:
    assert page.document is not None
    return _presence(page, "meta description", page.document.meta_description)


@check("F025")
def description_uniqueness(page: PageContext, ctx: Ctx) -> Outcome:
    assert page.document is not None
    return _uniqueness(
        page, page.document.meta_description, ctx.description_index, "meta description"
    )


@check("F026")
def description_alignment(page: PageContext, ctx: Ctx) -> Outcome:
    doc = page.document
    assert doc is not None
    if not doc.meta_description or not doc.meta_description.strip():
        return not_applicable("The page has no meta description.")
    description_terms = terms(doc.meta_description)
    if not description_terms:
        return not_applicable("The description has no content terms.")
    if not doc.text.strip():
        return not_applicable("The page has no extracted text to compare with.")
    covered = len(description_terms & terms(doc.text)) / len(description_terms)
    minimum = ctx.config.description_term_coverage_min
    if covered >= minimum:
        return passed(
            f"{covered:.0%} of description terms appear in the text.",
            round(covered, 3),
            f">= {minimum}",
        )
    return failed(
        f"Only {covered:.0%} of description terms appear in the text.",
        (obs(page, f'meta description: "{doc.meta_description}"'),),
        round(covered, 3),
        f">= {minimum}",
    )


@check("F027")
def language_declaration(page: PageContext, ctx: Ctx) -> Outcome:
    assert page.document is not None
    lang = page.document.language
    if lang is None:
        return failed(
            "No lang attribute on <html>.",
            (obs(page, "no <html lang>"),),
            None,
            "BCP 47 tag",
        )
    if not _LANG.match(lang.strip()):
        return failed(
            "The lang attribute is blank or malformed.",
            (obs(page, f'<html lang="{lang}">'),),
            lang,
            "BCP 47 tag",
        )
    return passed(
        "A well-formed language tag is declared.",
        lang,
        "BCP 47 tag",
        (obs(page, f'<html lang="{lang}">'),),
    )


@check("F028", requires="fetch")
def charset_declaration(page: PageContext, ctx: Ctx) -> Outcome:
    if page.fetch.outcome == "transport_error":
        return not_measured("No HTTP response, so headers are unknown.")
    content_type = page.fetch.headers.get("content-type", "")
    if re.search(r"charset\s*=", content_type, re.I):
        return passed(
            "The Content-Type header declares a charset.",
            content_type,
            "charset declared",
            (obs(page, f"Content-Type: {content_type}"),),
        )
    doc = page.document
    if doc is None or doc.detail_level < 2:
        return not_measured(
            "No charset in Content-Type, and <meta charset> was not extracted for this page."
        )
    if doc.charset_declared:
        return passed(
            "A <meta> charset is declared.",
            doc.charset_declared,
            "charset declared",
            (obs(page, f"meta charset: {doc.charset_declared}"),),
        )
    return failed(
        "No charset in the Content-Type header or a <meta> tag.",
        (obs(page, f"Content-Type: {content_type or '(none)'}; no <meta charset>"),),
        None,
        "charset declared",
    )


@check("F030", requires="document", version=2)
def snippet_restrictions(page: PageContext, ctx: Ctx) -> Outcome:
    assert page.document is not None
    meta = page.document.meta_robots
    header = page.fetch.headers.get("x-robots-tag")
    tokens = robots_directives(meta, header)
    restrictive = [t for t in tokens if t == "nosnippet" or t == "max-snippet:0"]
    if restrictive:
        source = f'meta robots "{meta}"' if meta else f'X-Robots-Tag "{header}"'
        return warned(
            f"Snippet use is restricted ({', '.join(restrictive)}). Confirm intent: "
            "this is correct when the page should not be quoted.",
            (obs(page, source),),
            restrictive,
            [],
            intent_severity(page, ctx.graph.entry),
        )
    return passed("No snippet restriction found.", [], [])
