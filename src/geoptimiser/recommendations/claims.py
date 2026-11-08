"""Rejecting text that promises outcomes this platform cannot support.

The platform records only the expected *direction* of impact (ADR-0002); it never
promises a numeric or guaranteed visibility result. These checks are deliberately
blunt: a false positive is a recommendation held back for a human to reword, a false
negative would be an unsupported promise in a customer-facing document.
"""

import re
from collections.abc import Iterable

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("percentage", re.compile(r"\d[\d.,]*\s*(?:%|per\s?cent|percent)", re.I)),
    ("multiplier", re.compile(r"\b\d+(?:\.\d+)?\s*(?:x|×|-fold|times)\b", re.I)),
    (
        "multiplier word",
        re.compile(
            r"\b(?:double|doubling|triple|tripling|tenfold|exponential)\b", re.I
        ),
    ),
    (
        "guarantee",
        re.compile(
            r"\b(?:guarantee[sd]?|assured|ensure[sd]? (?:that )?(?:you|your|the)\b)",
            re.I,
        ),
    ),
    (
        "certain outcome",
        re.compile(
            r"\b(?:will|would definitely|is certain to|are certain to)\s+"
            r"(?:definitely\s+)?(?:increase|improve|boost|raise|grow|rank|appear"
            r"|be cited|get cited)",
            re.I,
        ),
    ),
    (
        "ranking promise",
        re.compile(r"(?:#\s?1\b|\btop spot\b|\bfirst page\b|\bnumber one\b)", re.I),
    ),
)
_URL = re.compile(r"https?://[^\s<>\")\]]+")


# Website-derived values that templates interpolate: crawled URLs (affected pages) and
# quoted page text such as a noscript notice. They are data, not claims the platform
# makes, so they are removed before the claim patterns run. Otherwise a page named
# /save-50%25 or /top%2010%20tips would hold back every recommendation that lists it
# (security audit run 1, claim-screen finding).
_QUOTED = re.compile(r'"[^"\n]{0,400}"')


def authored_text(text: str) -> str:
    """``text`` with crawled URLs and quoted page excerpts removed."""
    return _QUOTED.sub(" ", _URL.sub(" ", text))


def claim_problems(text: str) -> list[str]:
    """Names of the unsupported-claim patterns found in ``text`` (empty if none)."""
    return [name for name, pattern in _PATTERNS if pattern.search(text)]


def urls_in(text: str) -> list[str]:
    return [u.rstrip(".,;:") for u in _URL.findall(text)]


def ungrounded_urls(text: str, allowed: Iterable[str]) -> list[str]:
    """URLs in ``text`` that are not among the sources the claim may rest on."""
    ok = {u.rstrip("/") for u in allowed}
    return [u for u in urls_in(text) if u.rstrip("/") not in ok]
