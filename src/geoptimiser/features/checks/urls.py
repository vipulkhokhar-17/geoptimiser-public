"""Category B: URL health and canonicalization."""

import re
from urllib.parse import parse_qsl, urljoin, urlsplit

from geoptimiser.features.checks._common import (
    clip,
    internal_host,
    obs,
    robots_directives,
)
from geoptimiser.features.context import Ctx, text_hash
from geoptimiser.features.inputs import PageContext, url_key
from geoptimiser.features.outcome import (
    Outcome,
    failed,
    not_applicable,
    not_measured,
    passed,
)
from geoptimiser.features.registry import check

_UUID = re.compile(
    r"^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$"
)
_LONG_HEX = re.compile(r"^[0-9a-f]{16,}$")


def _canonical(page: PageContext) -> str | None:
    assert page.document is not None
    value = page.document.canonical_url
    return value.strip() if value and value.strip() else None


@check("F011")
def canonical_presence(page: PageContext, ctx: Ctx) -> Outcome:
    assert page.document is not None
    value = page.document.canonical_url
    if value is None:
        return failed(
            "No rel=canonical link was found.",
            (obs(page, "no rel=canonical link"),),
            None,
            "present",
        )
    if not value.strip():
        return failed(
            "The canonical link has a blank href.",
            (obs(page, "rel=canonical href is blank"),),
            "",
            "present",
        )
    return passed(
        "A canonical URL is declared.",
        value,
        "present",
        (obs(page, f"canonical: {value}"),),
    )


# Statuses that say "the request was refused or throttled", not "the page is gone".
_ACCESS_STATUSES = frozenset({401, 403, 407, 429})


@check("F012", version=2)
def canonical_validity(page: PageContext, ctx: Ctx) -> Outcome:
    declared = _canonical(page)
    if declared is None:
        return not_applicable("The page declares no canonical URL (see F011).")
    resolved = urljoin(page.url, declared)
    parts = urlsplit(resolved)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.fragment:
        return failed(
            "The canonical is not an absolute http(s) URL without a fragment.",
            (obs(page, f"canonical: {declared}"),),
            resolved,
            "absolute http(s) URL, no fragment",
        )
    target = ctx.page_for(resolved)
    well_formed = "The canonical is well-formed (absolute http(s), no fragment)"
    if target is None:
        return not_measured(
            f"{well_formed}, but its target ({resolved}) was not crawled, so "
            "whether it exists and is indexable is unknown."
        )
    fetch = target.fetch
    if fetch.outcome == "transport_error":
        return not_measured(
            f"{well_formed}, but its target ({resolved}) could not be fetched "
            f"({fetch.error_type}), so whether it exists is unknown."
        )
    if fetch.outcome == "redirect_not_followed":
        return not_measured(
            f"{well_formed}, but its target ({resolved}) redirected and the "
            f"redirect was not followed ({fetch.redirect_refusal_reason})."
        )
    status = fetch.status_code
    if fetch.outcome == "http_error" and (
        (status or 0) >= 500 or status in _ACCESS_STATUSES
    ):
        return not_measured(
            f"{well_formed}, but its target ({resolved}) answered HTTP {status}, "
            "which says the request was refused or the server failed, not that the "
            "page is missing."
        )
    if fetch.outcome != "success":
        return failed(
            f"The canonical target answered HTTP {status}.",
            (
                obs(page, f"canonical: {declared}"),
                obs(target, f"HTTP status {status}"),
            ),
            {"canonical": resolved, "target_status": status},
            "target 2xx",
        )
    if target.document and {"noindex", "none"} & set(
        robots_directives(target.document.meta_robots)
    ):
        return failed(
            "The canonical target forbids indexing.",
            (
                obs(page, f"canonical: {declared}"),
                obs(target, f'meta robots: "{target.document.meta_robots}"'),
            ),
            {"canonical": resolved, "target_noindex": True},
            "target indexable",
        )
    return passed(
        "The canonical is well-formed and its crawled target is healthy.",
        {"canonical": resolved, "target_crawled": True},
        "healthy target",
        (obs(page, f"canonical: {declared}"),),
    )


@check("F013")
def canonical_consistency(page: PageContext, ctx: Ctx) -> Outcome:
    declared = _canonical(page)
    if declared is None:
        return not_applicable("The page declares no canonical URL.")
    resolved = url_key(urljoin(page.url, declared))
    if resolved == page.key:
        return passed(
            "The canonical points to the page itself.",
            "self",
            "self or self-canonical target",
            (obs(page, f"canonical: {declared}"),),
        )
    target = ctx.page_for(resolved)
    if target is None or target.document is None:
        return not_measured(
            "The canonical points to a page that was not crawled with a document."
        )
    other = target.document.canonical_url
    if (
        not other
        or not other.strip()
        or url_key(urljoin(target.url, other.strip())) == target.key
    ):
        return passed(
            "The canonical target is self-canonical.",
            "target self-canonical",
            "self or self-canonical target",
            (obs(page, f"canonical: {declared}"),),
        )
    return failed(
        "The canonical target itself canonicalises to a different URL (a chain or loop).",
        (obs(page, f"canonical: {declared}"), obs(target, f"canonical: {other}")),
        "chain",
        "self or self-canonical target",
    )


@check("F014")
def duplicate_content(page: PageContext, ctx: Ctx) -> Outcome:
    assert page.document is not None
    text = page.document.text
    if len(" ".join(text.split())) < ctx.config.duplicate_min_text_chars:
        return not_applicable("Too little text to compare reliably.")
    group = ctx.text_hash_index.get(text_hash(text), [])
    others = [p for p in group if p.key != page.key]
    digest = text_hash(text)[:12]
    if not others:
        return passed("No other crawled page has identical text.", [], [])
    return failed(
        f"{len(others)} other page(s) have identical text.",
        (
            obs(page, f"text SHA-256 {digest}…"),
            *[obs(o, f"identical text SHA-256 {digest}…") for o in others[:5]],
        ),
        [o.url for o in others],
        [],
    )


@check("F015", requires="fetch", version=2)
def redirect_chain(page: PageContext, ctx: Ctx) -> Outcome:
    hops = page.fetch.redirects
    if not hops:
        return not_applicable("The request was not redirected.")
    limit = ctx.config.max_redirect_hops
    if len(hops) <= limit:
        return passed(f"{len(hops)} redirect hop(s).", len(hops), f"<= {limit}")
    chain = " → ".join([str(hops[0].url), *(h.location for h in hops)])
    return failed(
        f"{len(hops)} redirect hops (configured limit {limit}).",
        (obs(page, f"redirect chain: {chain}"),),
        len(hops),
        f"<= {limit}",
    )


@check("F016", requires="fetch")
def redirect_loop(page: PageContext, ctx: Ctx) -> Outcome:
    hops = page.fetch.redirects
    if not hops:
        return not_applicable("The request was not redirected.")
    visited = {url_key(str(page.fetch.requested_url))}
    chain = [str(page.fetch.requested_url)]
    for hop in hops:
        target = urljoin(str(hop.url), hop.location)
        chain.append(target)
        if url_key(target) in visited:
            return failed(
                "The redirect chain revisits a URL.",
                (obs(page, " → ".join(chain)),),
                True,
                False,
            )
        visited.add(url_key(target))
    return passed("No URL repeats in the redirect chain.", False, False)


def _unverifiable(target: PageContext) -> bool:
    """A crawled target whose status says "refused or failing", not "missing"."""
    fetch = target.fetch
    status = fetch.status_code or 0
    return fetch.outcome == "http_error" and (
        status >= 500 or status in _ACCESS_STATUSES
    )


def broken_internal_links(
    page: PageContext, ctx: Ctx
) -> tuple[int, list[tuple[str, int | None]]]:
    """(links whose target was crawled, those among them that returned an error)."""
    checked, broken = 0, []
    seen: set[str] = set()
    for link in ctx.graph.internal_links.get(page.key, ()):
        target_key = ctx.graph.alias.get(link)
        if target_key is None or target_key in seen:
            continue
        seen.add(target_key)
        target = ctx.graph.nodes[target_key]
        if _unverifiable(target):
            continue  # refused, throttled or failing server: not evidence of a broken link
        checked += 1
        if target.fetch.outcome == "http_error":
            broken.append((target.url, target.fetch.status_code))
    return checked, broken


@check("F017", version=2)
def broken_links(page: PageContext, ctx: Ctx) -> Outcome:
    checked, broken = broken_internal_links(page, ctx)
    if checked == 0:
        return not_measured("None of this page's internal link targets were crawled.")
    if not broken:
        return passed(
            f"All {checked} crawled link targets are healthy.",
            {"checked": checked, "broken": []},
            0,
        )
    return failed(
        f"{len(broken)} of {checked} crawled link targets returned an HTTP error.",
        tuple(
            obs(page, f"links to {url} (HTTP {status})") for url, status in broken[:5]
        ),
        {"checked": checked, "broken": [u for u, _ in broken]},
        0,
    )


def _param_count(url: str) -> int:
    return len(parse_qsl(urlsplit(url).query, keep_blank_values=True))


@check("F018", requires="fetch", version=2)
def url_parameters(page: PageContext, ctx: Ctx) -> Outcome:
    """Query-parameter count of the page URL and of the internal URLs it links to.

    The crawler does not fetch URLs with query strings by default, so judging only the
    fetched URL could never fail; the linked URLs are inspected without being crawled.
    """
    own = _param_count(page.url)
    linked: list[tuple[str, int]] = []
    if page.document is not None:
        linked = [
            (link, _param_count(link))
            for link in page.document.links
            if urlsplit(link).query and internal_host(link, ctx.inputs.site_domain)
        ]
    limit = ctx.config.max_query_parameters
    heavy = [(u, n) for u, n in linked if n > limit]
    worst = max([own, *(n for _, n in linked)])
    observed = {
        "parameters": own,
        "internal_links_with_query": len(linked),
        "max_parameters_in_linked_urls": max((n for _, n in linked), default=0),
    }
    if own <= limit and not heavy:
        return passed(
            f"At most {worst} query parameter(s) in the page URL and its internal "
            "link targets.",
            observed,
            f"<= {limit}",
        )
    evidence = []
    if own > limit:
        evidence.append(obs(page, f"URL: {clip(page.url)}"))
    evidence += [
        obs(page, f"links to {clip(u)} ({n} parameters)") for u, n in heavy[:5]
    ]
    return failed(
        f"{worst} query parameters in the page URL or an internal link target "
        f"(configured limit {limit}).",
        tuple(evidence),
        observed,
        f"<= {limit}",
    )


def _unreadable(segment: str, max_chars: int) -> bool:
    stem = segment.rsplit(".", 1)[0] if "." in segment else segment
    lowered = stem.lower()
    digits = sum(c.isdigit() for c in lowered)
    return (
        len(segment) > max_chars
        or bool(_UUID.match(lowered))
        or bool(_LONG_HEX.match(lowered))
        or (len(lowered) >= 6 and digits / len(lowered) >= 0.5)
    )


@check("F019", requires="fetch")
def url_readability(page: PageContext, ctx: Ctx) -> Outcome:
    segments = [s for s in urlsplit(page.url).path.split("/") if s]
    if not segments:
        return not_applicable("The root URL has no path segments.")
    bad = [s for s in segments if _unreadable(s, ctx.config.max_url_segment_chars)]
    if not bad:
        return passed("All path segments look readable.", [], [])
    return failed(
        f"Unreadable path segment(s): {', '.join(clip(b, 40) for b in bad)}.",
        (obs(page, f"URL path: {urlsplit(page.url).path}"),),
        bad,
        [],
    )


@check("F020", requires="fetch")
def https_consistency(page: PageContext, ctx: Ctx) -> Outcome:
    fetch = page.fetch
    if fetch.final_url is None:
        return not_measured("There is no final URL to inspect.")
    insecure: list[str] = []
    if page.document is not None:
        insecure = [
            link
            for link in page.document.links
            if link.startswith("http://")
            and internal_host(link, ctx.inputs.site_domain)
        ]
    scheme = urlsplit(page.url).scheme
    if scheme != "https":
        return failed(
            "The page is served over HTTP.",
            (obs(page, f"final URL scheme: {scheme}"),),
            {"scheme": scheme, "insecure_internal_links": len(insecure)},
            "https",
        )
    if insecure:
        return failed(
            f"{len(insecure)} internal link(s) use http://.",
            tuple(obs(page, f"links to {clip(u)}") for u in insecure[:5]),
            {"scheme": scheme, "insecure_internal_links": len(insecure)},
            "https",
        )
    limits = (
        ()
        if page.document is not None
        else ("Links were not inspected: no extracted document.",)
    )
    return Outcome(
        "pass",
        "HTTPS with no insecure internal links.",
        {"scheme": scheme, "insecure_internal_links": 0},
        "https",
        limitations=limits,
    )
