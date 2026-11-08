"""Brand and competitor annotation of visibility observations (Stage 06)."""

import re
from collections.abc import Iterable, Sequence
from typing import Self
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from geoptimiser.schemas import (
    NonBlankStr,
    SchemaModel,
    VisibilityObservation,
    normalize_domain,
)

ANNOTATOR_VERSION = 1


class Entity(SchemaModel):
    """A brand or competitor: names seen in text, domains that may be cited."""

    name: NonBlankStr = Field(min_length=2)
    aliases: tuple[NonBlankStr, ...] = ()
    domains: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _normalise(self) -> Self:
        if any(len(a) < 2 for a in self.aliases):
            raise ValueError("aliases must have at least two characters")
        object.__setattr__(
            self, "domains", tuple(normalize_domain(d) for d in self.domains)
        )
        return self

    @property
    def terms(self) -> tuple[str, ...]:
        return (self.name, *self.aliases, *self.domains)


class BrandSpec(SchemaModel):
    brand: Entity
    competitors: tuple[Entity, ...] = ()

    @model_validator(mode="after")
    def _unique(self) -> Self:
        names = [e.name.lower() for e in (self.brand, *self.competitors)]
        if len(set(names)) != len(names):
            raise ValueError("brand and competitor names must be distinct")
        return self


def mentions(text: str, entity: Entity) -> bool:
    """Whole-word, case-insensitive match of the name, an alias or a domain in ``text``.

    "Acme" does not match "Acmeville". A name that is also an ordinary word (for example
    "Notion" or "Stripe") cannot be disambiguated by this rule; that is a documented
    limitation, not something the annotator resolves.
    """
    return any(
        re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE)
        for term in entity.terms
    )


def _host_matches(url: str, domain: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == domain or host.endswith("." + domain)


def cited_urls(observation: VisibilityObservation, entity: Entity) -> list[str]:
    """Citation URLs (fragment removed) that point at the entity's domains."""
    found = []
    for citation in observation.citations:
        if any(_host_matches(citation.url, d) for d in entity.domains):
            found.append(citation.url.split("#", 1)[0])
    return found


def annotate(
    observation: VisibilityObservation, spec: BrandSpec
) -> VisibilityObservation:
    """Return the observation with brand and competitor mentions set.

    Only successful observations are annotated; a failed or skipped one is returned
    unchanged, so a missing answer never becomes ``brand_mentioned=False``.
    """
    if observation.collection_status != "success":
        return observation
    text = observation.response_text
    return VisibilityObservation.model_validate(
        observation.model_dump()
        | {
            "brand_mentioned": mentions(text, spec.brand),
            "competitors_mentioned": [
                c.name for c in spec.competitors if mentions(text, c)
            ],
        }
    )


def annotate_all(
    observations: Iterable[VisibilityObservation], spec: BrandSpec
) -> list[VisibilityObservation]:
    return [annotate(o, spec) for o in observations]


def entity_names(entities: Sequence[Entity]) -> list[str]:
    return [e.name for e in entities]
