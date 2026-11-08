"""Category E: evidence, accuracy, trust and freshness (from structured data and links)."""

from datetime import UTC, datetime
from urllib.parse import urlsplit

from geoptimiser.features.checks._common import entities, internal_host, obs, types_of
from geoptimiser.features.context import Ctx, has_value
from geoptimiser.features.inputs import PageContext
from geoptimiser.features.outcome import Outcome, failed, not_applicable, passed
from geoptimiser.features.registry import check


def _articles(page: PageContext, ctx: Ctx) -> list[dict]:  # type: ignore[type-arg]
    assert page.document is not None
    article_types = set(ctx.config.article_types)
    return [e for e in entities(page.document) if article_types & set(types_of(e))]


@check("F041")
def source_citations(page: PageContext, ctx: Ctx) -> Outcome:
    doc = page.document
    assert doc is not None
    if len(doc.text) < ctx.config.min_text_chars_for_citation_check:
        return not_applicable("The page has too little text for a citation check.")
    external = sorted(
        {
            urlsplit(link).hostname or ""
            for link in doc.links
            if not internal_host(link, ctx.inputs.site_domain)
        }
    )
    if external:
        return passed(
            f"Links to {len(external)} external domain(s).",
            external[:10],
            ">= 1 external domain",
        )
    return failed(
        "The page links to no external domain.",
        (obs(page, f"{len(doc.links)} links, none external"),),
        [],
        ">= 1 external domain",
    )


@check("F046")
def author_attribution(page: PageContext, ctx: Ctx) -> Outcome:
    articles = _articles(page, ctx)
    if not articles:
        return not_applicable("The page declares no Article-type structured data.")
    missing = [i for i, a in enumerate(articles) if not has_value(a.get("author"))]
    if missing:
        return failed(
            "An Article entity has no author property.",
            (obs(page, f"Article entity #{missing[0] + 1} has no author"),),
            "missing",
            "author present",
        )
    return passed(
        "Article structured data names an author.", "present", "author present"
    )


@check("F047")
def publisher_identity(page: PageContext, ctx: Ctx) -> Outcome:
    assert page.document is not None
    items = entities(page.document)
    if not items:
        return not_applicable("The page has no structured data to inspect.")
    for item in items:
        if "Organization" in types_of(item) and has_value(item.get("name")):
            return passed(
                "An Organization with a name is declared.",
                item["name"],
                "named publisher",
            )
        publisher = item.get("publisher")
        if isinstance(publisher, dict) and has_value(publisher.get("name")):
            return passed(
                "A publisher with a name is declared.",
                publisher["name"],
                "named publisher",
            )
        if isinstance(publisher, str) and publisher.strip():
            return passed("A publisher is declared.", publisher, "named publisher")
    return failed(
        "Structured data is present but names no Organization or publisher.",
        (obs(page, f"{len(items)} structured-data entities, none naming a publisher"),),
        "missing",
        "named publisher",
    )


@check("F048")
def publication_date(page: PageContext, ctx: Ctx) -> Outcome:
    articles = _articles(page, ctx)
    if not articles:
        return not_applicable("The page declares no Article-type structured data.")
    if any(has_value(a.get("datePublished")) for a in articles):
        return passed("datePublished is declared.", "present", "present")
    return failed(
        "Article structured data has no datePublished.",
        (obs(page, "Article entity without datePublished"),),
        "missing",
        "present",
    )


@check("F049")
def modification_date(page: PageContext, ctx: Ctx) -> Outcome:
    articles = _articles(page, ctx)
    if not articles:
        return not_applicable("The page declares no Article-type structured data.")
    header = page.fetch.headers.get("last-modified")
    if any(has_value(a.get("dateModified")) for a in articles) or header:
        return passed("A modification date is available.", "present", "present")
    return failed(
        "No dateModified in structured data and no Last-Modified header.",
        (obs(page, "Article entity without dateModified; no Last-Modified header"),),
        "missing",
        "present",
    )


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@check("F050")
def freshness_consistency(page: PageContext, ctx: Ctx) -> Outcome:
    for article in _articles(page, ctx):
        published, modified = article.get("datePublished"), article.get("dateModified")
        if not has_value(published) or not has_value(modified):
            continue
        p, m = _parse(published), _parse(modified)
        problems = []
        if p is None or m is None:
            problems.append("a date is not ISO 8601")
        else:
            if m < p:
                problems.append("dateModified is earlier than datePublished")
            if max(p, m) > page.fetch.completed_at:
                problems.append("a date lies after the fetch time")
        if problems:
            return failed(
                "; ".join(problems).capitalize() + ".",
                (obs(page, f"datePublished={published}, dateModified={modified}"),),
                problems,
                [],
            )
        return passed("Dates are valid and ordered.", [], [])
    return not_applicable("No Article entity has both datePublished and dateModified.")
