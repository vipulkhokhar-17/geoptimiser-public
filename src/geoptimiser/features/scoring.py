"""Deterministic scoring that never rewards missing data (ADR-0012).

Definitions
-----------
* A *unit* is one ``FeatureResult``. ``pass`` counts 1, ``fail`` 0, ``warning`` 0.5.
  ``not_applicable`` units are removed. ``not_measured`` and ``error`` units are not
  scored but lower *coverage*.
* A feature's ``pass_rate`` is its mean unit score over measured units (``None`` if
  it has none). Only features with ``scored=True`` in the catalog take part.
* A group's (category, pillar, overall) ``score`` is the unweighted mean of its
  measured scored features' pass rates (``None`` if there are none).
* ``feature_coverage`` = measured scored features / scored features that could apply.
  Unimplemented features always count as "could apply" and as unmeasured; an
  implemented feature that is ``not_applicable`` on every unit is removed.
* ``unit_coverage`` = measured units / (measured + not_measured + error units).
* ``reportable`` is true only when ``feature_coverage`` reaches
  ``min_reportable_coverage`` (inclusive); a score below it must not be presented as a
  headline. ``reported_score`` is the score *as it may be shown*: ``score`` when
  reportable, else ``None``. ``score`` itself is kept for transparency only, and every
  consumer (HTML report, UI, comparison) must show ``reported_score``.
* A feature that cannot discriminate under the audit's crawl configuration, or a
  result that repeats another result's root cause, does not contribute
  (``contribution.py`` states each rule); it stays visible with its reason, and leaves the
  numerator and denominator alike, as a ``not_applicable`` unit does (ADR-0026).
"""

from collections import Counter
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from geoptimiser.features.catalog import FeatureCatalog
from geoptimiser.features.config import FeatureConfig
from geoptimiser.features.contribution import feature_exclusions, redundant_units
from geoptimiser.features.inputs import CrawlFacts
from geoptimiser.schemas import FeatureResult

SCORING_VERSION = 2
_CREDIT = {"pass": 1.0, "warning": 0.5, "fail": 0.0}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FeatureScore(_Model):
    feature_id: str
    scored: bool
    implementation_status: str
    passed: int
    failed: int
    warned: int
    not_applicable: int
    not_measured: int
    errors: int
    pass_rate: float | None
    applicable: bool
    # False: the feature is visible but not part of any aggregate (see contribution.py).
    contributes: bool = True
    exclusion_reason: str | None = None
    # Units dropped from the rate because they repeat another feature's result.
    redundant_units: int = 0


GroupStatus = Literal[
    "reportable", "withheld_low_coverage", "not_measured", "no_applicable_features"
]


class GroupScore(_Model):
    key: str
    name: str
    # The computed mean over the measured subset. Not for headlines unless reportable.
    score: float | None
    # What may be displayed: ``score`` if reportable, else None (with ``withheld_reason``).
    reported_score: float | None = None
    status: GroupStatus = "no_applicable_features"
    withheld_reason: str | None = None
    scored_features: int
    applicable_features: int
    measured_features: int
    feature_coverage: float | None
    unit_coverage: float | None
    reportable: bool
    note: str


class ScoreReport(_Model):
    scoring_version: int
    catalog_version: int
    min_reportable_coverage: float
    overall: GroupScore
    pillars: tuple[GroupScore, ...]
    categories: tuple[GroupScore, ...]
    features: tuple[FeatureScore, ...]
    # Features kept out of the aggregate -> why (they remain visible in `features`).
    excluded_features: dict[str, str] = {}


def _feature_scores(
    results: Sequence[FeatureResult],
    catalog: FeatureCatalog,
    exclusions: dict[str, str],
    redundant: set[tuple[str, str | None]],
) -> list[FeatureScore]:
    out: list[FeatureScore] = []
    for defn in catalog.features:
        all_own = [r for r in results if r.feature_id == defn.feature_id]
        own = [r for r in all_own if (r.feature_id, r.subject_url) not in redundant]
        counts = Counter(r.status for r in own)
        measured = [r for r in own if r.status in _CREDIT]
        rate = (
            sum(_CREDIT[r.status] for r in measured) / len(measured)
            if measured
            else None
        )
        applicable = not (
            defn.measurable_now
            and all_own
            and all(r.status == "not_applicable" for r in own)
        )
        out.append(
            FeatureScore(
                feature_id=defn.feature_id,
                scored=defn.scored,
                implementation_status=defn.implementation_status,
                passed=counts["pass"],
                failed=counts["fail"],
                warned=counts["warning"],
                not_applicable=counts["not_applicable"],
                not_measured=counts["not_measured"],
                errors=counts["error"],
                pass_rate=None if rate is None else round(rate, 4),
                applicable=applicable,
                contributes=defn.feature_id not in exclusions,
                exclusion_reason=exclusions.get(defn.feature_id),
                redundant_units=len(all_own) - len(own),
            )
        )
    return out


def _group(
    key: str, name: str, scores: Sequence[FeatureScore], config: FeatureConfig
) -> GroupScore:
    scored = [s for s in scores if s.scored and s.contributes]
    applicable = [s for s in scored if s.applicable]
    measured = [s for s in applicable if s.pass_rate is not None]
    units_measured = sum(s.passed + s.failed + s.warned for s in applicable)
    units_open = sum(s.not_measured + s.errors for s in applicable)
    value = (
        round(
            sum(s.pass_rate for s in measured if s.pass_rate is not None)
            / len(measured),
            4,
        )
        if measured
        else None
    )
    fc = round(len(measured) / len(applicable), 4) if applicable else None
    uc = (
        round(units_measured / (units_measured + units_open), 4)
        if units_measured + units_open
        else None
    )
    reportable = (
        fc is not None and fc >= config.min_reportable_coverage and value is not None
    )
    counts = f"{len(measured)} of {len(applicable)} applicable scored features"
    if value is None:
        note = "Nothing in this group was measured, so no score is given."
        status: GroupStatus = "not_measured" if applicable else "no_applicable_features"
        withheld = (
            f"No score: none of the {len(applicable)} applicable scored features "
            "was measured."
            if applicable
            else "No score: no scored feature applies to this group."
        )
    elif not reportable:
        note = (
            f"Only {counts} were measured; this score is shown for transparency "
            "and is not reportable."
        )
        status = "withheld_low_coverage"
        withheld = (
            f"Score withheld: only {counts} were measured (coverage "
            f"{fc:.0%}, minimum {config.min_reportable_coverage:.0%}). The computed "
            "value covers a subset and must not be read as a result for the group."
        )
    else:
        note = f"{counts} were measured."
        status = "reportable"
        withheld = None
    return GroupScore(
        key=key,
        name=name,
        score=value,
        reported_score=value if reportable else None,
        status=status,
        withheld_reason=withheld,
        scored_features=len(scored),
        applicable_features=len(applicable),
        measured_features=len(measured),
        feature_coverage=fc,
        unit_coverage=uc,
        reportable=reportable,
        note=note,
    )


def score_audit(
    results: Sequence[FeatureResult],
    catalog: FeatureCatalog,
    config: FeatureConfig | None = None,
    crawl: CrawlFacts | None = None,
) -> ScoreReport:
    """Score an audit. ``crawl`` says how pages were discovered (None: unknown)."""
    config = config or FeatureConfig()
    exclusions = feature_exclusions(config, crawl)
    redundant = set(redundant_units(results, config))
    features = _feature_scores(results, catalog, exclusions, redundant)
    by_id = {f.feature_id: f for f in features}
    categories = tuple(
        _group(
            c.code,
            c.name,
            [by_id[f.feature_id] for f in catalog.by_category(c.code)],
            config,
        )
        for c in catalog.categories
    )
    pillar_names: dict[str, str] = {
        "technical_health": "Technical health",
        "content_quality": "Content quality",
        "retrieval_readiness": "Retrieval readiness",
        "ai_visibility": "Observed AI visibility",
    }
    pillars = tuple(
        _group(
            key,
            name,
            [by_id[f.feature_id] for f in catalog.features if f.pillar == key],
            config,
        )
        for key, name in pillar_names.items()
    )
    overall = _group(
        "overall", "Overall (unweighted mean of feature pass rates)", features, config
    )
    return ScoreReport(
        scoring_version=SCORING_VERSION,
        catalog_version=catalog.version,
        min_reportable_coverage=config.min_reportable_coverage,
        overall=overall,
        pillars=pillars,
        categories=categories,
        features=tuple(features),
        excluded_features=exclusions,
    )
