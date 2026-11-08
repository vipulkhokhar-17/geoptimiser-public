"""What a check returns: a status, a value, and the observations that justify it."""

from dataclasses import dataclass
from typing import Any

from geoptimiser.schemas import FeatureStatus, Severity


@dataclass(frozen=True)
class Obs:
    """One observation to cite: a real value (or a stated absence) at a real URL."""

    url: str
    text: str


@dataclass(frozen=True)
class Outcome:
    status: FeatureStatus
    explanation: str
    observed: Any = None
    expected: Any = None
    evidence: tuple[Obs, ...] = ()
    severity: Severity | None = None
    limitations: tuple[str, ...] = ()


def passed(
    explanation: str,
    observed: Any = None,
    expected: Any = None,
    evidence: tuple[Obs, ...] = (),
) -> Outcome:
    return Outcome("pass", explanation, observed, expected, evidence)


def failed(
    explanation: str,
    evidence: tuple[Obs, ...],
    observed: Any = None,
    expected: Any = None,
    severity: Severity | None = None,
) -> Outcome:
    """A failure must cite what was observed; an uncited failure is a check bug."""
    if not evidence:
        raise ValueError("a failing result must cite at least one observation")
    return Outcome("fail", explanation, observed, expected, evidence, severity)


def warned(
    explanation: str,
    evidence: tuple[Obs, ...],
    observed: Any = None,
    expected: Any = None,
    severity: Severity | None = None,
) -> Outcome:
    """An observed condition that may be deliberate: reported, not scored as a defect.

    The explanation must say that intent should be confirmed. Like a failure, it must
    cite what was observed.
    """
    if not evidence:
        raise ValueError("a warning must cite at least one observation")
    return Outcome("warning", explanation, observed, expected, evidence, severity)


def not_applicable(reason: str) -> Outcome:
    return Outcome("not_applicable", reason)


def not_measured(reason: str) -> Outcome:
    return Outcome("not_measured", reason)
