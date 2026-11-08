"""Which results may move an aggregate score, and which only repeat another result.

A score is only meaningful if each underlying problem counts once and each feature that
contributes can actually tell a good page from a bad one. Two kinds of rules apply; both
leave the per-feature results, evidence and findings fully visible and only decide what
is *averaged*:

* **Feature exclusions** remove a whole feature from the aggregate because, under the
  audit's configuration and crawl, it cannot discriminate (it passes by construction).
* **Unit overlaps** remove individual results of a secondary feature that report the
  same root cause as a result of a primary feature on the same URL.

Each rule states its reason; reports show them. See docs/validation/VALIDATION_POLICY.md.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from geoptimiser.features.checks.structure import NO_MAIN
from geoptimiser.features.config import FeatureConfig
from geoptimiser.features.inputs import CrawlFacts
from geoptimiser.schemas import FeatureResult


def feature_exclusions(
    config: FeatureConfig, crawl: CrawlFacts | None
) -> dict[str, str]:
    """Features that cannot discriminate under this configuration -> why.

    Only decided from facts about *how pages were discovered*; with unknown discovery
    (``crawl is None``) nothing is assumed and nothing is excluded.
    """
    out: dict[str, str] = {}
    if crawl is None or crawl.discovery != "links":
        return out
    out["F009"] = (
        "Pages are discovered by following links from the entry page, so every crawled "
        "page has an incoming link by construction; orphan detection needs another "
        "discovery source such as a sitemap (F008)."
    )
    if config.min_incoming_links <= 1:
        out["F072"] = (
            "With a minimum of "
            f"{config.min_incoming_links} incoming link(s) this repeats F009 and "
            "cannot fail on a link-discovered page."
        )
    if crawl.max_depth is not None and crawl.max_depth <= config.max_click_depth:
        out["F010"] = (
            f"The crawl stopped at depth {crawl.max_depth}, which is not beyond the "
            f"limit of {config.max_click_depth} clicks, so no crawled page can exceed "
            "it; deeper pages were not crawled."
        )
    return out


@dataclass(frozen=True)
class UnitOverlap:
    """Results of ``secondary`` that only repeat results of other features.

    ``covered_by`` gets the secondary result and the other features' results on the
    same URL and returns the feature whose finding should carry the repeated failure
    (``None``: this result is independent and counts on its own).
    """

    secondary: str
    reason: str
    covered_by: Callable[[FeatureResult, Mapping[str, FeatureResult]], str | None]
    applies: Callable[[FeatureConfig], bool] = lambda config: True


@dataclass(frozen=True)
class Redundancy:
    rule: UnitOverlap
    home: str  # the feature whose result already counts this cause


def _same_status_as(primary: str) -> Callable[..., str | None]:
    def covered(
        result: FeatureResult, on_url: Mapping[str, FeatureResult]
    ) -> str | None:
        other = on_url.get(primary)
        measured = ("pass", "fail")
        if other and other.status == result.status and result.status in measured:
            return primary
        return None

    return covered


def _missing_main(
    result: FeatureResult, on_url: Mapping[str, FeatureResult]
) -> str | None:
    other = on_url.get("F052")
    only = result.status == "fail" and result.observed_value == [NO_MAIN]
    return "F052" if only and other and other.status == "fail" else None


_ARTICLE_PROPERTY_OWNER = {
    "author": "F046",
    "datePublished": "F048",
    "dateModified": "F049",
}
_LACKS = re.compile(r"lacks ([A-Za-z, ]+)")


def _article_metadata(
    result: FeatureResult, on_url: Mapping[str, FeatureResult]
) -> str | None:
    """F069 repeats F046/F048/F049 when every property it reports missing is one they
    already report missing on this URL; a missing headline is F069's own finding."""
    if result.status != "fail" or not isinstance(result.observed_value, list):
        return None
    missing: set[str] = set()
    for problem in result.observed_value:
        match = _LACKS.search(str(problem))
        if not match:
            return None
        missing |= {p.strip() for p in match.group(1).split(",") if p.strip()}
    if not missing or not missing <= set(_ARTICLE_PROPERTY_OWNER):
        return None
    homes = []
    for prop in sorted(missing):
        owner = on_url.get(_ARTICLE_PROPERTY_OWNER[prop])
        if owner is None or owner.status != "fail":
            return None
        homes.append(_ARTICLE_PROPERTY_OWNER[prop])
    return homes[0]


UNIT_OVERLAPS: tuple[UnitOverlap, ...] = (
    UnitOverlap(
        "F072",
        "F072 applies the same test as F009 when the minimum is 1 or less.",
        _same_status_as("F009"),
        applies=lambda config: config.min_incoming_links <= 1,
    ),
    UnitOverlap(
        "F059",
        "A page with no <main> landmark fails F052 and F059 for the same cause; it is "
        "counted once, under F052.",
        _missing_main,
    ),
    UnitOverlap(
        "F069",
        "Article metadata completeness repeats author (F046), datePublished (F048) and "
        "dateModified (F049) when those are what it reports missing; counted once, "
        "under the feature that names the property.",
        _article_metadata,
    ),
)


def redundant_units(
    results: Sequence[FeatureResult], config: FeatureConfig
) -> dict[tuple[str, str | None], Redundancy]:
    """(secondary feature id, subject url) -> the rule that makes it redundant."""
    by_url: dict[str | None, dict[str, FeatureResult]] = {}
    for r in results:
        by_url.setdefault(r.subject_url, {})[r.feature_id] = r
    out: dict[tuple[str, str | None], Redundancy] = {}
    for rule in UNIT_OVERLAPS:
        if not rule.applies(config):
            continue
        for result in results:
            if result.feature_id != rule.secondary:
                continue
            home = rule.covered_by(result, by_url[result.subject_url])
            if home is not None:
                out[(result.feature_id, result.subject_url)] = Redundancy(rule, home)
    return out
