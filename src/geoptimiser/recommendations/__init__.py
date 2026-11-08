"""Stage 10: deterministic recommendation generation and claim validation."""

from geoptimiser.recommendations.artifacts import write_outputs, write_recommendations
from geoptimiser.recommendations.claims import claim_problems, ungrounded_urls
from geoptimiser.recommendations.generator import (
    ImpactRule,
    RecommendationConfig,
    RecommendationGenerator,
    RecommendationSet,
    Rejected,
    TemplateGenerator,
    validate_recommendations,
)

__all__ = [
    "ImpactRule",
    "RecommendationConfig",
    "RecommendationGenerator",
    "RecommendationSet",
    "Rejected",
    "TemplateGenerator",
    "claim_problems",
    "ungrounded_urls",
    "validate_recommendations",
    "write_outputs",
    "write_recommendations",
]
