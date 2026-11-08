"""The versioned GEO feature catalog: contracts, validation and export.

The catalog is the product's stable vocabulary of measurable GEO features. Each
entry is a *definition* (what is measured, from which data, with what limits); it is
independent of whether a check for it exists yet. ``implementation_status`` says
honestly which entries execute today. See ADR-0011.
"""

import json
import re
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from geoptimiser.schemas import FeatureScope, ImplementationStatus, Severity

CATALOG_VERSION = 3

Pillar = Literal[
    "technical_health", "content_quality", "retrieval_readiness", "ai_visibility"
]
InputSource = Literal[
    "fetch_record",  # Stage 01 FetchRecord (status, headers, redirects, timing, size)
    "page_document",  # Stage 02 PageDocument
    "crawl_graph",  # link graph derived from the audit's documents and fetches
    "robots_txt",  # robots.txt bodies fetched by the crawler
    "stored_html",  # raw stored HTML (not yet exposed by Stage 02)
    "extractor_extension",  # a field Stage 02 does not extract yet
    "sitemap",  # sitemap files (the crawler does not fetch them yet)
    "external_http",  # fetching external URLs (not done by the crawler)
    "browser_render",  # rendered DOM / lab measurement
    "rum",  # real-user performance data
    "nlp_model",  # a language model or NLP component
    "ai_provider",  # AI-search provider responses (Stage 05)
    "query_benchmark",  # versioned query benchmark (Stage 04)
    "prior_audit",  # baseline audit for before/after comparison
    "site_configuration",  # user-supplied configuration (e.g. important pages)
]
# Sources that exist today; an implemented/partial check may use only these.
AVAILABLE_INPUTS: frozenset[str] = frozenset(
    {"fetch_record", "page_document", "crawl_graph", "robots_txt", "site_configuration"}
)
_ID = re.compile(r"^F\d{3}$")


class Overlap(BaseModel):
    """A neighbouring feature and how this one differs from it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    feature_id: str
    distinction: str = Field(min_length=10)


class Category(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(pattern=r"^[A-L]$")
    name: str
    description: str
    pillar: Pillar


class FeatureDefinition(BaseModel):
    """One catalog entry. Every field is documentation *and* contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    feature_id: str = Field(pattern=_ID.pattern)
    category: str = Field(pattern=r"^[A-L]$")
    name: str = Field(min_length=3)
    description: str = Field(min_length=20)
    rationale: str = Field(min_length=20)
    pillar: Pillar
    scope: FeatureScope
    measurement: str = Field(min_length=10)
    output_type: str = Field(min_length=3)
    unit: str | None = None
    inputs: tuple[InputSource, ...] = Field(min_length=1)
    evidence_requirements: str = Field(min_length=10)
    applicability: str = Field(min_length=10)
    method: str = Field(min_length=20)
    implementation_status: ImplementationStatus
    measurable_now: bool
    blocked_by: tuple[str, ...] = ()
    is_heuristic: bool = False
    # True when a violation may be a deliberate choice of the site owner (noindex,
    # blocked crawlers, snippet limits). Such features report `warning` ("confirm
    # intent"), are not scored, and raise a notice finding instead of a defect.
    intent_dependent: bool = False
    check_version: int = Field(default=0, ge=0)
    base_severity: Severity
    severity_policy: str = Field(min_length=10)
    scored: bool
    scoring_policy: str = Field(min_length=10)
    limitations: tuple[str, ...] = Field(min_length=1)
    config_keys: tuple[str, ...] = ()
    test_requirements: str = Field(min_length=10)
    remediation: str | None = None
    overlaps: tuple[Overlap, ...] = ()

    @model_validator(mode="after")
    def _check_honesty(self) -> "FeatureDefinition":
        runnable = self.implementation_status in ("implemented", "partial")
        if runnable != self.measurable_now:
            raise ValueError(
                f"{self.feature_id}: measurable_now must be true exactly when the "
                "status is implemented or partial"
            )
        if runnable:
            missing = set(self.inputs) - AVAILABLE_INPUTS
            if missing:
                raise ValueError(
                    f"{self.feature_id}: a runnable feature may not depend on "
                    f"unavailable inputs {sorted(missing)}"
                )
            if self.check_version < 1:
                raise ValueError(f"{self.feature_id}: check_version must be >= 1")
            if self.implementation_status == "partial" and not self.limitations:
                raise ValueError(f"{self.feature_id}: partial needs limitations")
        else:
            if not self.blocked_by:
                raise ValueError(
                    f"{self.feature_id}: a {self.implementation_status} feature "
                    "must say what blocks it"
                )
            if self.check_version != 0:
                raise ValueError(f"{self.feature_id}: no check, so check_version is 0")
        return self


class FeatureCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(ge=1)
    categories: tuple[Category, ...]
    features: tuple[FeatureDefinition, ...]

    @model_validator(mode="after")
    def _check_consistency(self) -> "FeatureCatalog":
        ids = [f.feature_id for f in self.features]
        duplicates = [i for i, n in Counter(ids).items() if n > 1]
        if duplicates:
            raise ValueError(f"duplicate feature ids: {duplicates}")
        codes = {c.code for c in self.categories}
        known = set(ids)
        for feature in self.features:
            if feature.category not in codes:
                raise ValueError(f"{feature.feature_id}: unknown category")
            for overlap in feature.overlaps:
                if overlap.feature_id not in known or overlap.feature_id == (
                    feature.feature_id
                ):
                    raise ValueError(
                        f"{feature.feature_id}: bad overlap {overlap.feature_id}"
                    )
        return self

    def get(self, feature_id: str) -> FeatureDefinition:
        for feature in self.features:
            if feature.feature_id == feature_id:
                return feature
        raise KeyError(feature_id)

    def by_category(self, code: str) -> tuple[FeatureDefinition, ...]:
        return tuple(f for f in self.features if f.category == code)

    def by_status(self, status: ImplementationStatus) -> tuple[FeatureDefinition, ...]:
        return tuple(f for f in self.features if f.implementation_status == status)

    def to_json(self) -> str:
        """Stable, sorted-by-id JSON for ``configs/feature_catalog.json``."""
        return (
            json.dumps(self.model_dump(mode="json"), indent=2, ensure_ascii=False)
            + "\n"
        )
