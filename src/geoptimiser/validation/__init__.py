"""Repeatable validation of the audit pipeline against deterministic local fixtures.

A *fixture* is a small mock website plus **expectations written down in advance**:
what each feature should report for each page, which findings must (not) exist and
how the scores must be reported. ``run_fixture`` drives the real crawler, extractor,
feature checks, scoring, diagnosis and recommendations against the mock site;
``evaluate_fixture`` compares the outcome with the expectations. Nothing here touches
the public network.

The expectations come from the written validation policy (docs/validation), not from
running the implementation and copying what it printed.
"""

from geoptimiser.validation.evaluate import (
    ExpectationResult,
    FixtureEvaluation,
    evaluate_fixture,
)
from geoptimiser.validation.metrics import BinaryCounts, wilson_interval
from geoptimiser.validation.runner import FixtureRun, run_fixture
from geoptimiser.validation.spec import FixtureSpec, load_fixture, load_fixtures

__all__ = [
    "BinaryCounts",
    "ExpectationResult",
    "FixtureEvaluation",
    "FixtureRun",
    "FixtureSpec",
    "evaluate_fixture",
    "load_fixture",
    "load_fixtures",
    "run_fixture",
    "wilson_interval",
]
