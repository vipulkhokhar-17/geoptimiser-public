"""Category K: delivery characteristics of the page response."""

import re

from geoptimiser.features.checks._common import obs
from geoptimiser.features.context import Ctx
from geoptimiser.features.inputs import PageContext
from geoptimiser.features.outcome import Outcome, failed, not_measured, passed
from geoptimiser.features.registry import check


def _no_response(page: PageContext) -> Outcome | None:
    if page.fetch.outcome == "transport_error":
        return not_measured(f"No HTTP response was received ({page.fetch.error_type}).")
    return None


@check("F101", requires="fetch")
def response_latency(page: PageContext, ctx: Ctx) -> Outcome:
    if (missing := _no_response(page)) is not None:
        return missing
    seconds = (page.fetch.completed_at - page.fetch.started_at).total_seconds()
    budget = ctx.config.latency_budget_seconds
    if seconds <= budget:
        return passed(
            f"The fetch took {seconds:.2f}s.", round(seconds, 3), f"<= {budget}s"
        )
    return failed(
        f"The fetch took {seconds:.2f}s (budget {budget}s).",
        (obs(page, f"fetch duration {seconds:.2f}s"),),
        round(seconds, 3),
        f"<= {budget}s",
    )


@check("F102", requires="fetch")
def response_size(page: PageContext, ctx: Ctx) -> Outcome:
    body = page.fetch.body
    if body is None:
        return not_measured(
            f"No stored body ({page.fetch.body_not_stored_reason or page.fetch.outcome})."
        )
    limit = ctx.config.max_html_bytes
    observed = {"bytes": body.size_bytes, "truncated": body.truncated}
    if body.truncated or body.size_bytes > limit:
        return failed(
            "The HTML response was truncated or larger than the configured size.",
            (obs(page, f"{body.size_bytes} bytes stored; truncated={body.truncated}"),),
            observed,
            f"<= {limit} bytes, complete",
        )
    return passed(f"{body.size_bytes} bytes.", observed, f"<= {limit} bytes, complete")


@check("F104", requires="fetch")
def cache_headers(page: PageContext, ctx: Ctx) -> Outcome:
    if (missing := _no_response(page)) is not None:
        return missing
    value = page.fetch.headers.get("cache-control", "").strip()
    if value:
        return passed(
            "Cache-Control is set.",
            value,
            "present",
            (obs(page, f"Cache-Control: {value}"),),
        )
    return failed(
        "No Cache-Control header.",
        (obs(page, "no Cache-Control header"),),
        None,
        "present",
    )


@check("F105", requires="fetch")
def validators(page: PageContext, ctx: Ctx) -> Outcome:
    if (missing := _no_response(page)) is not None:
        return missing
    found = {
        n: page.fetch.headers[n]
        for n in ("etag", "last-modified")
        if page.fetch.headers.get(n)
    }
    if found:
        return passed(
            "A validator header is present.",
            sorted(found),
            "ETag or Last-Modified",
            (obs(page, ", ".join(f"{k}: {v}" for k, v in found.items())),),
        )
    return failed(
        "Neither ETag nor Last-Modified is present.",
        (obs(page, "no ETag or Last-Modified header"),),
        [],
        "ETag or Last-Modified",
    )


_MAX_AGE = re.compile(r'(?:^|;)\s*max-age\s*=\s*"?(\d{1,12})"?\s*(?:;|$)', re.I)


def hsts_max_age(value: str) -> int | None:
    """The max-age of a Strict-Transport-Security value (RFC 6797 6.1.1), or None.

    Exactly one max-age directive is required; a duplicate makes the header invalid.
    """
    found = _MAX_AGE.findall(value)
    if len(found) != 1 or len(re.findall(r"max-age", value, re.I)) != 1:
        return None
    return int(found[0])


@check("F110", requires="fetch")
def transport_security(page: PageContext, ctx: Ctx) -> Outcome:
    if (missing := _no_response(page)) is not None:
        return missing
    final = page.fetch.final_url or page.fetch.requested_url
    scheme = final.scheme
    raw = page.fetch.headers.get("strict-transport-security", "").strip()
    max_age = hsts_max_age(raw) if raw else None
    observed = {"scheme": scheme, "hsts": raw or None, "max_age": max_age}
    expected = "https with Strict-Transport-Security max-age > 0"
    if scheme != "https":
        return failed(
            "The page was served over plain HTTP.",
            (obs(page, f"final URL scheme: {scheme}"),),
            observed,
            expected,
        )
    if not raw:
        return failed(
            "HTTPS, but no Strict-Transport-Security header.",
            (obs(page, "no Strict-Transport-Security header"),),
            observed,
            expected,
        )
    if max_age is None or max_age == 0:
        why = (
            "max-age=0 (the policy is cleared)"
            if max_age == 0
            else "no single valid max-age directive"
        )
        return failed(
            f"HTTPS, but the Strict-Transport-Security header is not usable: {why}.",
            (obs(page, f"Strict-Transport-Security: {raw}"),),
            observed,
            expected,
        )
    return passed(
        f"HTTPS with Strict-Transport-Security (max-age={max_age}).",
        observed,
        expected,
        (obs(page, f"Strict-Transport-Security: {raw}"),),
    )
