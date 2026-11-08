"""Day 6: the local-first application layer over the existing audit pipeline.

Importing this package needs neither FastAPI nor LangGraph; those load only when the API
is created or an agent run is requested.
"""

from geoptimiser.app.compare import CompareError, Comparison, compare_reports
from geoptimiser.app.config import AppConfig
from geoptimiser.app.models import (
    PIPELINE_VERSION,
    AuditOptions,
    AuditRecord,
    AuditSubmission,
    TargetError,
    normalize_target,
)
from geoptimiser.app.pipeline import PipelineDeps, run_pipeline
from geoptimiser.app.report import AuditReport, render_html
from geoptimiser.app.service import AuditService, ServiceError
from geoptimiser.app.store import AuditStore

__all__ = [
    "PIPELINE_VERSION",
    "AppConfig",
    "AuditOptions",
    "AuditRecord",
    "AuditReport",
    "AuditService",
    "AuditStore",
    "AuditSubmission",
    "CompareError",
    "Comparison",
    "PipelineDeps",
    "ServiceError",
    "TargetError",
    "compare_reports",
    "normalize_target",
    "render_html",
    "run_pipeline",
]
