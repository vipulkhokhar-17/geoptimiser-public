"""Check registration and lookup. Adding a feature = adding a function and an entry."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from geoptimiser.features.catalog import FeatureCatalog
from geoptimiser.features.outcome import Outcome

# "rich_document": a document extracted at detail level >= 2 (images, anchors, ...).
Requires = Literal["fetch", "document", "rich_document", "none"]
# A site-scope check returns one Outcome or several (subject URL, Outcome) units.
Unit = tuple[str | None, Outcome]


@dataclass(frozen=True)
class Check:
    feature_id: str
    scope: Literal["page", "site"]
    requires: Requires
    version: int
    fn: Callable[..., Any]


CHECKS: dict[str, Check] = {}


def check(
    feature_id: str,
    *,
    scope: Literal["page", "site"] = "page",
    requires: Requires = "document",
    version: int = 1,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a check. Page checks take ``(page, ctx)``; site checks take ``(ctx)``."""

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        if feature_id in CHECKS:
            raise ValueError(f"duplicate check for {feature_id}")
        CHECKS[feature_id] = Check(feature_id, scope, requires, version, fn)
        return fn

    return decorate


class FeatureRegistry:
    """The catalog plus the checks that implement part of it."""

    def __init__(self, catalog: FeatureCatalog, checks: dict[str, Check]) -> None:
        self.catalog = catalog
        self.checks = dict(checks)
        self.validate()

    def validate(self) -> None:
        """Registry and catalog must agree about what is implemented."""
        for feature in self.catalog.features:
            has_check = feature.feature_id in self.checks
            if feature.measurable_now and not has_check:
                raise ValueError(
                    f"{feature.feature_id} is {feature.implementation_status} but has no check"
                )
            if not feature.measurable_now and has_check:
                raise ValueError(
                    f"{feature.feature_id} is {feature.implementation_status} but has a check"
                )
            if has_check:
                registered = self.checks[feature.feature_id]
                if registered.scope != feature.scope:
                    raise ValueError(
                        f"{feature.feature_id}: check scope differs from catalog"
                    )
                if registered.version != feature.check_version:
                    raise ValueError(
                        f"{feature.feature_id}: check version differs from catalog"
                    )
        unknown = set(self.checks) - {f.feature_id for f in self.catalog.features}
        if unknown:
            raise ValueError(f"checks for unknown features: {sorted(unknown)}")

    def implemented_ids(self) -> list[str]:
        return [
            f.feature_id for f in self.catalog.features if f.feature_id in self.checks
        ]


def default_registry() -> FeatureRegistry:
    """The production registry: the shipped catalog and all registered checks."""
    from geoptimiser.features import checks  # noqa: F401  (import registers them)
    from geoptimiser.features.catalog_data import CATALOG

    return FeatureRegistry(CATALOG, CHECKS)
