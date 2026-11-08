"""Stage 02: HTML extraction from stored fetch bodies into ``PageDocument`` records."""

from geoptimiser.extraction.artifacts import ExtractionWriter, read_documents
from geoptimiser.extraction.config import EXTRACTION_VERSION, ExtractionConfig
from geoptimiser.extraction.pipeline import (
    ExtractionResult,
    SkippedFetch,
    extract_all,
    extract_fetch,
    skip_reason,
)

__all__ = [
    "EXTRACTION_VERSION",
    "ExtractionConfig",
    "ExtractionResult",
    "ExtractionWriter",
    "SkippedFetch",
    "extract_all",
    "extract_fetch",
    "read_documents",
    "skip_reason",
]
