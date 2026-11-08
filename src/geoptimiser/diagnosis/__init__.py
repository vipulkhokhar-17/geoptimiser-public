"""Stage 09: evidence-linked diagnosis."""

from geoptimiser.diagnosis.artifacts import write_diagnosis
from geoptimiser.diagnosis.engine import (
    Diagnosis,
    DiagnosisConfig,
    DiagnosisError,
    diagnose,
    validate_diagnosis,
)
from geoptimiser.diagnosis.grounding import (
    GroundingError,
    passage_evidence,
    validate_grounding,
)
from geoptimiser.diagnosis.rules import DEFAULT_RULES, SynthesisRule, validate_rules

__all__ = [
    "DEFAULT_RULES",
    "Diagnosis",
    "DiagnosisConfig",
    "DiagnosisError",
    "GroundingError",
    "SynthesisRule",
    "diagnose",
    "passage_evidence",
    "validate_diagnosis",
    "validate_grounding",
    "validate_rules",
    "write_diagnosis",
]
