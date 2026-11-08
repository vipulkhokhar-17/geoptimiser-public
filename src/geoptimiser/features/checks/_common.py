"""Helpers shared by several checks."""

from typing import Any
from urllib.parse import urlsplit

from geoptimiser.features.inputs import PageContext
from geoptimiser.features.outcome import Obs
from geoptimiser.schemas import PageDocument, Severity

_CLIP = 200


def clip(value: str, limit: int = _CLIP) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def obs(page: PageContext, text: str) -> Obs:
    """An observation about ``page`` at its URL."""
    return Obs(page.url, clip(text) or "(empty)")


_PARAMETERISED = (
    "max-snippet",
    "max-image-preview",
    "max-video-preview",
    "unavailable_after",
)


def robots_directives(*values: str | None) -> list[str]:
    """Lower-case directive tokens from meta robots / X-Robots-Tag values.

    An optional leading ``agent:`` scope (``googlebot: noindex``) is dropped;
    parameterised directives such as ``max-snippet:0`` are kept whole.
    """
    tokens: list[str] = []
    for value in values:
        for part in (value or "").lower().split(","):
            part = part.strip()
            name, sep, rest = part.partition(":")
            if sep and name.strip() in _PARAMETERISED:
                tokens.append(f"{name.strip()}:{rest.strip()}")
                continue
            if sep:  # "agent: directive"
                part = rest.strip()
            tokens.extend(part.split())
    return tokens


def entities(document: PageDocument) -> list[dict[str, Any]]:
    """Top-level JSON-LD objects plus the members of their ``@graph``."""
    found: list[dict[str, Any]] = []
    for item in document.structured_data:
        graph = item.get("@graph")
        rest = {k: v for k, v in item.items() if k != "@graph"}
        if any(k != "@context" for k in rest):
            found.append(item)
        if isinstance(graph, list):
            found.extend(m for m in graph if isinstance(m, dict))
    return found


def types_of(entity: dict[str, Any]) -> list[str]:
    """``@type`` values reduced to their last path segment (schema.org/Product -> Product)."""
    raw = entity.get("@type")
    values = raw if isinstance(raw, list) else [raw]
    return [
        v.rstrip("/").rsplit("/", 1)[-1] for v in values if isinstance(v, str) and v
    ]


def internal_host(url: str, domain: str) -> bool:
    from geoptimiser.crawler.urls import host_in_scope

    return host_in_scope(urlsplit(url).hostname or "", domain)


def intent_severity(page: PageContext, entry_key: str | None) -> Severity:
    """Severity of a notice about an owner-controlled directive.

    Intent cannot be known, so the notice is ``low``; it is ``medium`` on the entry
    page, where the same directive would hide the whole site.
    """
    return "medium" if page.key == entry_key else "low"
