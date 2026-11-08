"""Category A: crawlability and discovery."""

from geoptimiser.crawler.robots import RobotsPolicy, parse_rules
from geoptimiser.features.checks._common import (
    intent_severity,
    obs,
    robots_directives,
)
from geoptimiser.features.context import Ctx
from geoptimiser.features.inputs import PageContext
from geoptimiser.features.outcome import (
    Obs,
    Outcome,
    failed,
    not_applicable,
    not_measured,
    passed,
    warned,
)
from geoptimiser.features.registry import Unit, check


@check("F001", requires="fetch", version=2)
def http_success(page: PageContext, ctx: Ctx) -> Outcome:
    fetch = page.fetch
    # v2: a rate-limit answer (429), or a 503 that says when to retry, describes how the
    # server treated this crawl at this moment, not the page. Reporting it as a page
    # failure would invent a defect from a missing measurement.
    if fetch.outcome == "http_error" and (
        fetch.status_code == 429
        or (fetch.status_code == 503 and fetch.headers.get("retry-after"))
    ):
        return not_measured(
            f"The server answered HTTP {fetch.status_code}"
            + (" with Retry-After" if fetch.status_code == 503 else "")
            + ": it asked the crawler to slow down or retry later, so the page's own status is unknown."
        )
    if fetch.outcome == "success":
        return passed(
            f"HTTP {fetch.status_code}",
            fetch.status_code,
            "2xx",
            (obs(page, f"HTTP status {fetch.status_code}"),),
        )
    if fetch.outcome == "http_error":
        return failed(
            f"The page returned HTTP {fetch.status_code}.",
            (obs(page, f"HTTP status {fetch.status_code}"),),
            fetch.status_code,
            "2xx",
        )
    if fetch.outcome == "redirect_not_followed":
        return not_measured(
            f"A redirect was not followed ({fetch.redirect_refusal_reason}); the final status is unknown."
        )
    return not_measured(f"No HTTP response was received ({fetch.error_type}).")


@check("F002")
def crawlable_links(page: PageContext, ctx: Ctx) -> Outcome:
    doc = page.document
    assert doc is not None
    if doc.detail_level >= 2:
        count = sum(1 for a in doc.anchors if "nofollow" not in a.rel)
        nofollow = len(doc.anchors) - count
        observed: object = {"followable": count, "nofollow": nofollow}
    else:  # older extraction: only the URL list is known
        count, observed = len(doc.links), {"followable": len(doc.links)}
    minimum = ctx.config.min_crawlable_links
    if count >= minimum:
        return passed(f"{count} followable links.", observed, minimum)
    return failed(
        f"The page has {count} followable links (minimum {minimum}); it is a dead end for crawlers.",
        (obs(page, f"{count} followable http(s) anchor links found"),),
        observed,
        minimum,
    )


def _robots_url(record) -> str:  # type: ignore[no-untyped-def]
    return str(record.final_url or record.requested_url)


@check("F003", scope="site", requires="none")
def robots_accessibility(ctx: Ctx) -> Outcome | list[Unit]:
    if not ctx.inputs.robots:
        return not_measured("The crawl did not fetch robots.txt.")
    units: list[Unit] = []
    for robots in ctx.inputs.robots:
        record, url = robots.record, _robots_url(robots.record)
        if record.outcome == "success" or (
            record.outcome == "http_error" and (record.status_code or 0) < 500
        ):
            note = (
                "readable"
                if record.outcome == "success"
                else "absent (treated as allow-all)"
            )
            units.append(
                (
                    url,
                    passed(
                        f"robots.txt is {note}.",
                        record.status_code,
                        "2xx or 4xx",
                        (Obs(url, f"robots.txt HTTP {record.status_code}"),),
                    ),
                )
            )
        elif record.outcome == "http_error":
            units.append(
                (
                    url,
                    failed(
                        f"robots.txt returned HTTP {record.status_code}; crawlers may treat the site as disallowed.",
                        (Obs(url, f"robots.txt HTTP {record.status_code}"),),
                        record.status_code,
                        "2xx or 4xx",
                    ),
                )
            )
        else:
            units.append(
                (
                    url,
                    not_measured(
                        "robots.txt could not be retrieved (no usable response)."
                    ),
                )
            )
    return units


@check("F004", requires="fetch", version=2)
def robots_compliance(page: PageContext, ctx: Ctx) -> Outcome:
    robots = ctx.inputs.robots_for(page.url)
    if robots is None:
        return not_measured("No robots.txt was fetched for this origin.")
    record = robots.record
    if record.outcome == "success":
        if record.body is not None and robots.text is None:
            return not_measured(
                "robots.txt was fetched but its stored body could not be read, so its "
                "rules are unknown (not treated as allow-all)."
            )
        text = robots.text or ""  # an empty body stores nothing: no restrictions
    elif record.outcome == "http_error" and (record.status_code or 0) < 500:
        text = ""  # absent: no restrictions
    else:
        return not_measured("robots.txt was unreadable, so its rules are unknown.")
    tokens = (*ctx.config.audit_agent_tokens, *ctx.config.ai_crawler_tokens)
    blocked = [
        t for t in tokens if not RobotsPolicy(parse_rules(text, t)).allows(page.url)
    ]
    if not blocked:
        if record.body is not None and record.body.truncated:
            return not_measured(
                "robots.txt was larger than the stored limit and was cut, so rules "
                "after the cut are unknown; no block was found in the part read."
            )
        return passed("robots.txt permits all configured agents.", [], [])
    return warned(
        f"robots.txt disallows this URL for: {', '.join(blocked)}. This may be a "
        "deliberate access policy; confirm intent before changing it.",
        (
            Obs(
                _robots_url(record),
                f"robots.txt disallows {page.url} for {', '.join(blocked)}",
            ),
        ),
        blocked,
        [],
        intent_severity(page, ctx.graph.entry),
    )


@check("F005", version=2)
def meta_robots(page: PageContext, ctx: Ctx) -> Outcome:
    assert page.document is not None
    tokens = robots_directives(page.document.meta_robots)
    blocking = sorted({"noindex", "none"} & set(tokens))
    if blocking:
        return warned(
            f"The meta robots tag asks search engines not to index this page "
            f"({', '.join(blocking)}). Confirm intent: this is correct for pages "
            "that should stay out of search results.",
            (obs(page, f'meta robots: "{page.document.meta_robots}"'),),
            tokens,
            "no noindex/none",
            intent_severity(page, ctx.graph.entry),
        )
    return passed("No indexing restriction in meta robots.", tokens, "no noindex/none")


@check("F006", requires="fetch", version=2)
def x_robots_tag(page: PageContext, ctx: Ctx) -> Outcome:
    fetch = page.fetch
    if fetch.outcome == "transport_error":
        return not_measured("No HTTP response, so headers are unknown.")
    header = fetch.headers.get("x-robots-tag")
    tokens = robots_directives(header)
    blocking = sorted({"noindex", "none"} & set(tokens))
    if blocking:
        return warned(
            f"The X-Robots-Tag header asks search engines not to index this page "
            f"({', '.join(blocking)}). Confirm intent: this is correct for pages "
            "that should stay out of search results.",
            (obs(page, f'X-Robots-Tag: "{header}"'),),
            tokens,
            "no noindex/none",
            intent_severity(page, ctx.graph.entry),
        )
    return passed("No indexing restriction in X-Robots-Tag.", tokens, "no noindex/none")


@check("F007", scope="site", requires="none")
def sitemap_declared(ctx: Ctx) -> Outcome:
    declared: list[tuple[str, str]] = []
    for robots in ctx.inputs.robots:
        for line in (robots.text or "").splitlines():
            name, _, value = line.split("#", 1)[0].partition(":")
            if name.strip().lower() == "sitemap" and value.strip():
                declared.append((_robots_url(robots.record), value.strip()))
    if declared:
        urls = [v for _, v in declared]
        return passed(
            f"{len(urls)} sitemap(s) declared in robots.txt.",
            urls,
            ">= 1 declared",
            tuple(Obs(src, f"Sitemap: {value}") for src, value in declared[:5]),
        )
    return not_measured(
        "No Sitemap directive in robots.txt; default sitemap locations are not probed, so absence is not concluded."
    )


def _uncertain_note(ctx: Ctx) -> str:
    n = len(ctx.uncertain_link_sources)
    return (
        f"{n} crawled page(s) have incomplete link lists (truncated, capped or not "
        "extracted); a link from one of them may point here"
    )


@check("F009", requires="fetch", version=2)
def orphan_risk(page: PageContext, ctx: Ctx) -> Outcome:
    graph = ctx.graph
    if page.key == graph.entry:
        return not_applicable("The entry page is not expected to have incoming links.")
    incoming = len(graph.incoming.get(page.key, ()))
    if incoming:
        return passed(f"{incoming} crawled page(s) link here.", incoming, ">= 1")
    if ctx.uncertain_link_sources:
        return not_measured(f"No read link points here, but {_uncertain_note(ctx)}.")
    return failed(
        "No other crawled page links to this page.",
        (obs(page, "0 incoming internal links from crawled pages"),),
        0,
        ">= 1",
    )


@check("F010", requires="fetch", version=2)
def crawl_depth(page: PageContext, ctx: Ctx) -> Outcome:
    depth = ctx.graph.depth.get(page.key)
    if depth is None:
        return not_measured(
            "The page is not reachable from the entry page through crawled links."
        )
    limit = ctx.config.max_click_depth
    if depth <= limit:
        return passed(f"{depth} click(s) from the entry page.", depth, f"<= {limit}")
    if ctx.uncertain_link_sources:
        return not_measured(
            f"The shortest path read is {depth} clicks (limit {limit}), but "
            f"{_uncertain_note(ctx)}, so a shorter path may exist."
        )
    return failed(
        f"{depth} clicks from the entry page (configured limit {limit}).",
        (obs(page, f"link distance from entry page: {depth}"),),
        depth,
        f"<= {limit}",
    )
