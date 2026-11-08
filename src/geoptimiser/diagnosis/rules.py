"""Cross-feature synthesis rules: deterministic, scoped to one page."""

from typing import Self

from pydantic import Field, model_validator

from geoptimiser.features.catalog import FeatureCatalog
from geoptimiser.schemas import Identifier, NonBlankStr, SchemaModel, Severity


class SynthesisRule(SchemaModel):
    """Fires on each page where **every** required feature has a failing result.

    A rule states a co-occurrence of measured failures, nothing more: it does not
    claim that the failures interact or cause an outcome.
    """

    rule_id: Identifier
    title: NonBlankStr
    description: NonBlankStr
    requires: tuple[Identifier, ...] = Field(min_length=2)
    severity: Severity
    remediation: NonBlankStr

    @model_validator(mode="after")
    def _distinct(self) -> Self:
        if len(set(self.requires)) != len(self.requires):
            raise ValueError("requires must not repeat a feature")
        return self


DEFAULT_RULES: tuple[SynthesisRule, ...] = (
    SynthesisRule(
        rule_id="no_page_summary",
        title="Page has neither a title nor a meta description",
        description=(
            "The page offers neither a title nor a meta description, so engines "
            "and users have no concise statement of what the page is about."
        ),
        requires=("F021", "F024"),
        severity="high",
        remediation="Add a descriptive title and a meta description to the page.",
    ),
    SynthesisRule(
        rule_id="hard_to_extract",
        title="Little extractable text and weak semantic markup",
        description=(
            "The page yields little main text and also lacks semantic HTML, "
            "which makes its content hard to extract and quote."
        ),
        requires=("F051", "F055"),
        severity="high",
        remediation=(
            "Serve the main content as server-rendered text inside semantic "
            "elements (main, article, section)."
        ),
    ),
    SynthesisRule(
        rule_id="poor_passage_structure",
        title="Broken heading hierarchy and weak section structure",
        description=(
            "The heading hierarchy is broken and the page does not split into "
            "self-describing sections, so passages are hard to retrieve on "
            "their own."
        ),
        requires=("F035", "F091"),
        severity="medium",
        remediation=(
            "Repair the heading order and give each section a descriptive heading."
        ),
    ),
)


def validate_rules(rules: tuple[SynthesisRule, ...], catalog: FeatureCatalog) -> None:
    """Rules must name distinct ids and only features that can actually fail."""
    known = {d.feature_id: d for d in catalog.features}
    if len({r.rule_id for r in rules}) != len(rules):
        raise ValueError("rule_ids must be unique")
    for rule in rules:
        for feature_id in rule.requires:
            defn = known.get(feature_id)
            if defn is None:
                raise ValueError(f"{rule.rule_id}: unknown feature {feature_id}")
            if defn.implementation_status not in ("implemented", "partial"):
                raise ValueError(
                    f"{rule.rule_id}: {feature_id} is not implemented, so the rule "
                    "could never fire"
                )
            if defn.scope != "page":
                raise ValueError(f"{rule.rule_id}: {feature_id} is not page-scoped")
