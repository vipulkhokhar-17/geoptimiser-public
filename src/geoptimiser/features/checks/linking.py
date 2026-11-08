"""Category H: internal linking and site architecture."""

from itertools import combinations

from geoptimiser.features.checks._common import internal_host, obs
from geoptimiser.features.checks.urls import broken_internal_links
from geoptimiser.features.context import Ctx, terms
from geoptimiser.features.inputs import PageContext
from geoptimiser.features.outcome import (
    Obs,
    Outcome,
    failed,
    not_applicable,
    not_measured,
    passed,
)
from geoptimiser.features.registry import check


@check("F071")
def link_density(page: PageContext, ctx: Ctx) -> Outcome:
    doc = page.document
    assert doc is not None
    if not doc.text.strip():
        return not_applicable("The page has no text to normalise by.")
    internal = len(ctx.graph.internal_links.get(page.key, ()))
    density = internal / (len(doc.text) / 1000)
    return passed(
        f"{internal} internal links, {density:.2f} per 1,000 characters.",
        round(density, 3),
        None,
        (obs(page, f"{internal} internal links in {len(doc.text)} characters"),),
    )


@check("F072", requires="fetch", version=2)
def incoming_links(page: PageContext, ctx: Ctx) -> Outcome:
    if page.key == ctx.graph.entry:
        return not_applicable("The entry page is not expected to have incoming links.")
    count = len(ctx.graph.incoming.get(page.key, ()))
    minimum = ctx.config.min_incoming_links
    if count >= minimum:
        return passed(f"{count} incoming link source(s).", count, f">= {minimum}")
    if ctx.uncertain_link_sources:
        return not_measured(
            f"{count} incoming link(s) were read (minimum {minimum}), but "
            f"{len(ctx.uncertain_link_sources)} crawled page(s) have incomplete link "
            "lists, so more links may exist."
        )
    return failed(
        f"{count} incoming link source(s) (minimum {minimum}).",
        (obs(page, f"{count} crawled pages link here"),),
        count,
        f">= {minimum}",
    )


@check("F073")
def outgoing_links(page: PageContext, ctx: Ctx) -> Outcome:
    doc = page.document
    assert doc is not None
    internal = sum(
        1 for link in doc.links if internal_host(link, ctx.inputs.site_domain)
    )
    external = len(doc.links) - internal
    return passed(
        f"{internal} internal and {external} external links.",
        {"internal": internal, "external": external},
        None,
        (obs(page, f"{internal} internal, {external} external links"),),
    )


@check("F079", scope="site", requires="none")
def broken_link_concentration(ctx: Ctx) -> Outcome:
    per_page: dict[str, list[tuple[str, int | None]]] = {}
    checked_total = 0
    for page in ctx.inputs.pages:
        if page.document is None:
            continue
        checked, broken = broken_internal_links(page, ctx)
        checked_total += checked
        if broken:
            per_page[page.url] = broken
    if checked_total == 0:
        return not_measured("No internal link targets were crawled.")
    total = sum(len(v) for v in per_page.values())
    if total == 0:
        return passed(
            "No broken internal links among crawled targets.", {"total_broken": 0}, 0
        )
    worst_url, worst = max(per_page.items(), key=lambda item: len(item[1]))
    summary = {
        "total_broken": total,
        "pages_affected": len(per_page),
        "worst_page_share": round(len(worst) / total, 3),
    }
    return failed(
        f"{total} broken internal link(s) on {len(per_page)} page(s); the worst page holds {summary['worst_page_share']:.0%}.",
        tuple(
            Obs(url, f"links to {t} (HTTP {s})")
            for url, items in list(per_page.items())[:5]
            for t, s in items[:1]
        ),
        summary,
        0,
    )


@check("F080", scope="site", requires="none")
def topic_redundancy(ctx: Ctx) -> Outcome:
    labelled = []
    for page in ctx.inputs.pages:
        doc = page.document
        if doc is None or not doc.title:
            continue
        h1 = next((h.text for h in doc.headings if h.level == 1), "")
        words = terms(f"{doc.title} {h1}")
        if len(words) >= 2:
            labelled.append((page, words))
    if len(labelled) < 2:
        return not_applicable("Fewer than two pages have a title with content terms.")
    limit = ctx.config.topic_overlap_max
    pairs = []
    for (a, ta), (b, tb) in combinations(labelled, 2):
        similarity = len(ta & tb) / len(ta | tb)
        if similarity >= limit:
            pairs.append((a, b, round(similarity, 3)))
    if not pairs:
        return passed(
            "No pair of pages has heavily overlapping title/H1 terms.", [], []
        )
    evidence = tuple(
        Obs(page.url, f"title/H1 terms overlap {sim:.0%} with {other.url}")
        for page, other, sim in pairs[:5]
    )
    return failed(
        f"{len(pairs)} pair(s) of pages have title/H1 term overlap >= {limit:.0%}.",
        evidence,
        [(a.url, b.url, s) for a, b, s in pairs],
        f"< {limit}",
    )
