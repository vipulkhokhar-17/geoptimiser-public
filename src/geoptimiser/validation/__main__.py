"""``python -m geoptimiser.validation``: run the fixture benchmark and print a summary.

    python -m geoptimiser.validation --fixtures tests/validation/fixtures \
        --out docs/validation/results/latest.json
"""

import argparse
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

from geoptimiser.validation.evaluate import FixtureEvaluation, evaluate_fixture
from geoptimiser.validation.metrics import BinaryCounts
from geoptimiser.validation.runner import run_fixture
from geoptimiser.validation.spec import load_fixtures


def summarize(evaluations: list[FixtureEvaluation]) -> dict[str, object]:
    total = sum(len(e.results) for e in evaluations)
    ok = sum(1 for e in evaluations for r in e.results if r.ok)
    per_feature: dict[str, BinaryCounts] = {}
    abstained: dict[str, dict[str, int]] = {}
    for e in evaluations:
        for fid, counts in e.counts.items():
            per_feature[fid] = per_feature.get(fid, BinaryCounts()) + counts
        for fid, a in e.abstained.items():
            bucket = abstained.setdefault(fid, {})
            for k, v in a.items():
                bucket[k] = bucket.get(k, 0) + v
    pairs = Counter(p for e in evaluations for p in e.state_pairs)
    unmeasurable = {"not_measured", "not_applicable"}
    return {
        "fixtures": len(evaluations),
        "fixtures_passed": sum(1 for e in evaluations if e.passed),
        "expectations": total,
        "expectations_met": ok,
        # Expected vs actual result state for every feature expectation.
        "state_confusion": {
            f"{expected} -> {actual}": n
            for (expected, actual), n in sorted(pairs.items())
        },
        # A website defect reported where the evidence could not support one...
        "false_failures_on_unmeasurable": sum(
            n for (e, a), n in pairs.items() if e in unmeasurable and a == "fail"
        ),
        # ...and a pass reported where the evidence could not support one.
        "silent_passes_on_unmeasurable": sum(
            n for (e, a), n in pairs.items() if e == "not_measured" and a == "pass"
        ),
        "per_feature_metrics": {
            fid: {**c.as_dict(), "abstained": abstained.get(fid, {})}
            for fid, c in sorted(per_feature.items())
        },
        "fixture_results": [
            {
                "fixture": e.fixture,
                "passed": e.passed,
                "expectations": len(e.results),
                "failures": [
                    {
                        "subject": r.subject,
                        "expected": r.expected,
                        "actual": r.actual,
                        "detail": r.detail,
                    }
                    for r in e.failures
                ],
            }
            for e in evaluations
        ],
        "note": (
            "Metrics come from synthetic fixtures with pre-declared expectations: "
            "they test measurement correctness on constructed cases, not accuracy "
            "on real websites."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the validation fixture benchmark."
    )
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--only", help="run only fixtures whose id contains this text")
    args = parser.parse_args(argv)
    specs = [
        s for s in load_fixtures(args.fixtures) if not args.only or args.only in s.id
    ]
    if not specs:
        print("no fixtures found", file=sys.stderr)
        return 2
    evaluations = []
    with tempfile.TemporaryDirectory() as tmp:
        for spec in specs:
            evaluations.append(evaluate_fixture(run_fixture(spec, Path(tmp))))
    summary = summarize(evaluations)
    for e in evaluations:
        verdict = "PASS" if e.passed else "FAIL"
        print(f"{verdict} {e.fixture} ({len(e.results)} expectations)")
        for r in e.failures:
            print(f"    - {r.kind} {r.subject}: expected {r.expected}, got {r.actual}")
            print(f"        {r.detail}")
    print(
        f"{summary['fixtures_passed']}/{summary['fixtures']} fixtures, "
        f"{summary['expectations_met']}/{summary['expectations']} expectations met"
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0 if all(e.passed for e in evaluations) else 1


if __name__ == "__main__":
    raise SystemExit(main())
