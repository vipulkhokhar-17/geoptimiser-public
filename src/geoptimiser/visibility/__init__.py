"""Stages 05–06: AI-search provider contract, visibility collection and metrics."""

from geoptimiser.visibility.annotate import BrandSpec, Entity, annotate, annotate_all
from geoptimiser.visibility.collect import (
    BudgetExceeded,
    CollectionConfig,
    CollectionManifest,
    CollectionResult,
    DraftQuerySet,
    collect_visibility,
)
from geoptimiser.visibility.metrics import (
    VisibilityMetrics,
    compute_metrics,
    write_metrics,
)
from geoptimiser.visibility.providers import (
    AnswerProvider,
    FixtureProvider,
    ProviderAnswer,
    ProviderError,
    ProviderRateLimited,
    ProviderResponseError,
    ProviderTimeout,
    ProviderUnavailable,
    ScriptedProvider,
    require_env,
)

__all__ = [
    "AnswerProvider",
    "BrandSpec",
    "BudgetExceeded",
    "CollectionConfig",
    "CollectionManifest",
    "CollectionResult",
    "DraftQuerySet",
    "Entity",
    "FixtureProvider",
    "ProviderAnswer",
    "ProviderError",
    "ProviderRateLimited",
    "ProviderResponseError",
    "ProviderTimeout",
    "ProviderUnavailable",
    "ScriptedProvider",
    "VisibilityMetrics",
    "write_metrics",
    "annotate",
    "annotate_all",
    "collect_visibility",
    "compute_metrics",
    "require_env",
]
