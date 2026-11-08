"""Stage 03: the GEO feature catalog, registry, deterministic checks, findings and scores."""

from geoptimiser.features.catalog import (
    CATALOG_VERSION,
    FeatureCatalog,
    FeatureDefinition,
)
from geoptimiser.features.catalog_data import CATALOG
from geoptimiser.features.config import FeatureConfig
from geoptimiser.features.engine import run_all, run_category, run_feature
from geoptimiser.features.findings import (
    EvidenceError,
    build_findings,
    collect_evidence,
    validate_provenance,
)
from geoptimiser.features.inputs import AuditInputs, PageContext, load_inputs
from geoptimiser.features.registry import FeatureRegistry, default_registry
from geoptimiser.features.scoring import ScoreReport, score_audit

__all__ = [
    "CATALOG",
    "CATALOG_VERSION",
    "AuditInputs",
    "EvidenceError",
    "FeatureCatalog",
    "FeatureConfig",
    "FeatureDefinition",
    "FeatureRegistry",
    "PageContext",
    "ScoreReport",
    "build_findings",
    "collect_evidence",
    "default_registry",
    "load_inputs",
    "run_all",
    "run_category",
    "run_feature",
    "score_audit",
    "validate_provenance",
]
