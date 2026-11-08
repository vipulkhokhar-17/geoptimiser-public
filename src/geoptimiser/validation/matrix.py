"""The 120-feature validation matrix, built from the catalog, the code and the judgments.

Facts (status, source location, thresholds, tests, how missing evidence is handled) are
derived from the repository so they cannot drift; assessments come from
``judgments.py``. ``python -m geoptimiser.validation.matrix --write`` regenerates
``docs/validation/feature_validation_matrix.csv`` and the generated section of
``docs/validation/GEOPTIMISER_FEATURE_AUDIT.md``; ``--check`` fails if they are stale or
if any catalog feature is missing, duplicated or unjudged.
"""

import argparse
import csv
import inspect
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from geoptimiser.features.catalog import FeatureDefinition
from geoptimiser.features.config import FeatureConfig
from geoptimiser.features.contribution import UNIT_OVERLAPS
from geoptimiser.features.evidence import POLICIES, SELF_MANAGED
from geoptimiser.features.registry import CHECKS, default_registry
from geoptimiser.validation.judgments import (
    INFO,
    INVESTIGATE,
    REMOVE,
    RETAIN,
    REVISE,
    THRESHOLDS,
    judgment_for,
)
from geoptimiser.validation.sources import by_id

ROOT = Path(__file__).resolve().parents[3]
DISPOSITIONS = (RETAIN, REVISE, INFO, REMOVE, INVESTIGATE)
BEGIN = "<!-- BEGIN GENERATED: feature register (python -m geoptimiser.validation.matrix --write) -->"
END = "<!-- END GENERATED -->"

COLUMNS = (
    "feature_id", "name", "category", "benefit_class", "purpose", "property_measured",
    "claimed_outcome", "claim_strength", "evidence_and_rationale", "source_refs",
    "applicability", "inputs", "implementation_status", "source_location",
    "default_configuration", "threshold_basis", "scoring_role", "existing_tests",
    "coverage_gaps", "potential_false_positives", "potential_false_negatives",
    "missing_evidence_behavior", "overlap_or_duplication", "discriminates_valid_from_invalid",
    "supports_actionable_recommendation", "claim_empirically_validated", "validation_status",
    "dimension_implementation_verified", "dimension_measurement_correctness_evaluated",
    "dimension_diagnostic_accuracy_benchmarked", "dimension_technical_rationale_supported",
    "dimension_ai_visibility_demonstrated", "dimension_business_outcome_demonstrated",
    "assessment_confidence", "disposition", "required_follow_up",
    "implementation_level", "validation_level", "disposition_code",
)  # fmt: skip
# The three separate classifications used by the final assignment (docs/project/
# FEATURE_VALIDATION_GUIDE.md). They are derived from the columns above, never typed.
IMPLEMENTATION_LEVELS = (
    "IMPLEMENTED",
    "PARTIAL",
    "PLANNED",
    "UNAVAILABLE",
    "NOT_VERIFIABLE",
)
VALIDATION_LEVELS = (
    "NOT_TESTED",
    "UNIT_TESTED",
    "FIXTURE_VALIDATED",
    "PIPELINE_VALIDATED",
    "REAL_PAGE_VALIDATED",
    "OUTCOME_VALIDATED",
)
DISPOSITION_CODES = {RETAIN: "RETAIN", REVISE: "REVISE", INFO: "INFORMATIONAL_ONLY",
                     REMOVE: "REMOVE", INVESTIGATE: "INVESTIGATE"}  # fmt: skip
LEVELS_PATH = Path(__file__).with_name("feature_levels.json")


def _tests_dir() -> Path:
    return ROOT / "tests"


def _test_mentions(feature_id: str) -> list[str]:
    pattern = re.compile(rf"\b{feature_id}\b")
    files = []
    for path in sorted(_tests_dir().rglob("*.py")):
        if pattern.search(path.read_text(encoding="utf-8")):
            files.append(path.relative_to(ROOT).as_posix())
    return files


def _fixture_mentions(feature_id: str) -> list[str]:
    pattern = re.compile(rf'"{feature_id}"|fnd_{feature_id}\b')
    out = []
    for path in sorted((_tests_dir() / "validation" / "fixtures").glob("*/spec.json")):
        if pattern.search(path.read_text(encoding="utf-8")):
            out.append(path.parent.name)
    return out


def _pipeline_expectations() -> set[str]:
    """Features with a page- or site-scope result expectation in a fixture that
    tests/validation/test_app_pipeline.py replays through the application and API."""
    from geoptimiser.validation.levels import APP_PIPELINE_NO_FEATURES

    out: set[str] = set()
    for path in sorted((_tests_dir() / "validation" / "fixtures").glob("*/spec.json")):
        if path.parent.name in APP_PIPELINE_NO_FEATURES:
            continue
        expect = json.loads(path.read_text(encoding="utf-8")).get("expect", {})
        for per_page in expect.get("pages", {}).values():
            out.update(per_page)
        out.update(expect.get("site", {}))
    return out


def _implementation_level(defn: FeatureDefinition) -> str:
    return {
        "implemented": "IMPLEMENTED",
        "partial": "PARTIAL",
        "planned": "PLANNED",
        "unavailable": "UNAVAILABLE",
    }.get(defn.implementation_status, "NOT_VERIFIABLE")


def _validation_level(
    runnable: bool, unit_tests: list[str], fixtures: list[str], pipeline: bool
) -> str:
    """Highest level reached. No feature has a labelled real-page benchmark or a
    measured outcome, so REAL_PAGE_VALIDATED and OUTCOME_VALIDATED are never derived
    here; they need a real corpus (benchmarks/corpus with real_world: true) first."""
    if not runnable:
        return "NOT_TESTED"
    if fixtures and pipeline:
        return "PIPELINE_VALIDATED"
    if fixtures:
        return "FIXTURE_VALIDATED"
    return "UNIT_TESTED" if unit_tests else "NOT_TESTED"


def _location(feature_id: str) -> str:
    check = CHECKS.get(feature_id)
    if check is None:
        return "(no check)"
    fn = check.fn
    _, line = inspect.getsourcelines(fn)
    return (
        f"{Path(inspect.getsourcefile(fn) or '').relative_to(ROOT).as_posix()}:{line}"
    )


def _config_text(defn: FeatureDefinition) -> str:
    config = FeatureConfig()
    parts = []
    for key in defn.config_keys:
        value = getattr(config, key)
        text = (
            json.dumps(value, default=list) if not isinstance(value, dict) else "{...}"
        )
        parts.append(f"{key}={text if len(text) < 90 else text[:87] + '...'}")
    parts.append(f"base severity {defn.base_severity}")
    return "; ".join(parts)


def _missing_evidence(defn: FeatureDefinition) -> str:
    fid = defn.feature_id
    if fid not in CHECKS:
        return "Not implemented: always not_measured (never a pass or a failure)."
    check = CHECKS[fid]
    notes = []
    if check.scope == "page" and check.requires in ("document", "rich_document"):
        notes.append(
            "no extracted document -> not_measured with the fetch/extraction reason"
        )
        if check.requires == "rich_document":
            notes.append("older extraction level -> not_measured")
    if fid in POLICIES:
        p = POLICIES[fid]
        fields = f" ({', '.join(p.fields)})" if p.fields else ""
        notes.append(
            f"truncated or limit-cut evidence{fields}: '{p.kind}' policy "
            "(what stays conclusive is stated in features/evidence.py)"
        )
        notes.append("interstitial/challenge page -> not_measured")
    elif fid in SELF_MANAGED:
        notes.append(SELF_MANAGED[fid])
    elif check.requires == "fetch":
        notes.append("no HTTP response -> not_measured where headers/body are needed")
    return (
        "; ".join(notes) or "reads only data that is always present for a fetched page"
    )


def _scoring_role(defn: FeatureDefinition) -> str:
    if not defn.measurable_now:
        return "not measured (excluded from scores)"
    if defn.intent_dependent:
        return "unscored notice (warning, confirm intent)"
    if not defn.scored:
        return "unscored (informational)"
    fid = defn.feature_id
    if fid in ("F009", "F072", "F010"):
        return "scored, but excluded from the aggregate when it cannot discriminate (see scoring policy)"
    for rule in UNIT_OVERLAPS:
        if rule.secondary == fid:
            return "scored; results that only repeat another feature's count once"
    return "scored"


def _supported(strength: str, sources: tuple[str, ...]) -> str:
    if strength.startswith("none"):
        return "n/a"
    if strength.startswith("specified"):
        if not sources:
            return "asserted, unverified (no source retrieved)"
        from geoptimiser.validation.sources import PRIMARY

        verified = [by_id()[s].verification == PRIMARY for s in sources]
        if all(verified):
            return "yes: primary specification or vendor page checked (2026-11-01)"
        if any(verified):
            return "partly: some sources checked on the primary page, others summaries"
        return "partly: sources are search-result summaries"
    if strength.startswith("plausible"):
        return "plausible mechanism, unverified"
    return "unsupported (hypothesis)"


def build_rows() -> list[dict[str, str]]:
    registry = default_registry()
    srcs = by_id()
    pipeline = _pipeline_expectations()
    rows = []
    for defn in registry.catalog.features:
        j = judgment_for(defn.feature_id)
        fid = defn.feature_id
        unit_tests = _test_mentions(fid)
        fixtures = _fixture_mentions(fid)
        runnable = defn.measurable_now
        gaps = []
        if runnable and not unit_tests:
            gaps.append("no unit test names this feature")
        if runnable and not fixtures:
            gaps.append("not exercised by a whole-pipeline fixture")
        if runnable:
            gaps.append("no labelled real-world benchmark (precision/recall unknown)")
        if defn.implementation_status == "partial":
            gaps.append("partial: " + defn.limitations[0])
        refs = "; ".join(f"{s} {srcs[s].title} <{srcs[s].url}>" for s in j.sources)
        if not runnable:
            status = "V0: not implemented; no check exists, always not_measured"
        elif fixtures:
            status = "V2: implemented; measurement evaluated against pre-declared synthetic fixtures; not benchmarked on real pages"
        else:
            status = "V1: implemented; unit-tested only; not evaluated by a whole-pipeline fixture or on real pages"
        verified = (
            "yes"
            if runnable and unit_tests
            else "no"
            if not runnable
            else "tests absent"
        )
        rows.append(
            {
                "feature_id": fid,
                "name": defn.name,
                "category": f"{defn.category} {next(c.name for c in registry.catalog.categories if c.code == defn.category)}",
                "benefit_class": j.benefit,
                "purpose": defn.description,
                "property_measured": defn.measurement
                if runnable
                else "(nothing: not implemented) " + defn.measurement,
                "claimed_outcome": j.claim,
                "claim_strength": j.strength,
                "evidence_and_rationale": defn.rationale,
                "source_refs": refs
                or ("none retrieved" if not runnable or j.sources == () else ""),
                "applicability": defn.applicability,
                "inputs": ", ".join(defn.inputs),
                "implementation_status": defn.implementation_status
                + (" (heuristic)" if defn.is_heuristic else ""),
                "source_location": _location(fid),
                "default_configuration": _config_text(defn),
                "threshold_basis": j.threshold_basis,
                "scoring_role": _scoring_role(defn),
                "existing_tests": "; ".join(unit_tests[:4])
                + (f" (+{len(unit_tests) - 4} more)" if len(unit_tests) > 4 else "")
                + ("; fixtures: " + ", ".join(fixtures) if fixtures else "")
                or "none",
                "coverage_gaps": "; ".join(gaps) or "n/a",
                "potential_false_positives": j.false_positives,
                "potential_false_negatives": j.false_negatives,
                "missing_evidence_behavior": _missing_evidence(defn),
                "overlap_or_duplication": j.overlap
                or "; ".join(f"{o.feature_id}: {o.distinction}" for o in defn.overlaps)
                or "none identified",
                "discriminates_valid_from_invalid": j.discriminates,
                "supports_actionable_recommendation": j.actionable,
                "claim_empirically_validated": "no",
                "validation_status": status,
                "dimension_implementation_verified": verified,
                "dimension_measurement_correctness_evaluated": (
                    f"synthetic fixtures ({len(fixtures)})"
                    if fixtures
                    else "unit tests only"
                    if unit_tests and runnable
                    else "no"
                ),
                "dimension_diagnostic_accuracy_benchmarked": "no (no labelled real-world corpus)",
                "dimension_technical_rationale_supported": _supported(
                    j.strength, j.sources
                ),
                "dimension_ai_visibility_demonstrated": "no",
                "dimension_business_outcome_demonstrated": "no",
                "assessment_confidence": j.confidence,
                "disposition": j.disposition,
                "required_follow_up": j.followup or "none beyond the general benchmark",
                "implementation_level": _implementation_level(defn),
                "validation_level": _validation_level(
                    runnable, unit_tests, fixtures, fid in pipeline
                ),
                "disposition_code": DISPOSITION_CODES[j.disposition],
            }
        )
    return rows


def completeness_problems(rows: list[dict[str, str]]) -> list[str]:
    """Everything that makes the matrix an unreliable account of the catalog."""
    catalog = default_registry().catalog
    problems = []
    ids = [r["feature_id"] for r in rows]
    for fid, n in Counter(ids).items():
        if n != 1:
            problems.append(f"{fid} appears {n} times")
    expected = [f.feature_id for f in catalog.features]
    for fid in expected:
        if fid not in ids:
            problems.append(f"{fid} is in the catalog but not in the matrix")
    for fid in ids:
        if fid not in expected:
            problems.append(f"{fid} is in the matrix but not in the catalog")
    status = {f.feature_id: f.implementation_status for f in catalog.features}
    for r in rows:
        if r["feature_id"] in status and not r["implementation_status"].startswith(
            status[r["feature_id"]]
        ):
            problems.append(
                f"{r['feature_id']}: implementation status differs from the catalog"
            )
        if r["disposition"] not in DISPOSITIONS:
            problems.append(
                f"{r['feature_id']}: unknown disposition {r['disposition']!r}"
            )
        for col in COLUMNS:
            if not str(r.get(col, "")).strip():
                problems.append(f"{r['feature_id']}: empty column {col}")
    return problems


def to_csv(rows: list[dict[str, str]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def summary_counts(rows: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "total": len(rows),
        "by_implementation": dict(
            Counter(r["implementation_status"].split(" ")[0] for r in rows)
        ),
        "by_disposition": dict(Counter(r["disposition"] for r in rows)),
        "by_validation_status": dict(
            Counter(r["validation_status"].split(":")[0] for r in rows)
        ),
        "by_implementation_level": {
            k: sum(1 for r in rows if r["implementation_level"] == k)
            for k in IMPLEMENTATION_LEVELS
        },
        # Cumulative: a PIPELINE_VALIDATED feature is also fixture- and unit-tested.
        "by_validation_level": {
            k: sum(1 for r in rows if r["validation_level"] == k)
            for k in VALIDATION_LEVELS
        },
        "at_least_validation_level": {
            k: sum(
                1 for r in rows if VALIDATION_LEVELS.index(r["validation_level"]) >= i
            )
            for i, k in enumerate(VALIDATION_LEVELS)
            if k != "NOT_TESTED"
        },
        "by_disposition_code": {
            k: sum(1 for r in rows if r["disposition_code"] == k)
            for k in DISPOSITION_CODES.values()
        },
        "by_scoring_role": dict(
            Counter(r["scoring_role"].split(" (")[0].split(",")[0] for r in rows)
        ),
    }


def generated_markdown(rows: list[dict[str, str]]) -> str:
    counts = summary_counts(rows)
    lines = [BEGIN, "", "### Counts", ""]
    lines += [f"* **Features accounted for:** {counts['total']} (F001-F120, each once)"]
    for title, key in (
        ("Implementation status (catalog)", "by_implementation"),
        ("Recommended disposition", "by_disposition"),
        ("Validation status", "by_validation_status"),
        ("Scoring role", "by_scoring_role"),
        ("Implementation level", "by_implementation_level"),
        ("Validation level (highest reached)", "by_validation_level"),
        ("Reached at least (cumulative)", "at_least_validation_level"),
        ("Disposition code", "by_disposition_code"),
    ):
        items = counts[key].items()
        if key in (
            "by_implementation",
            "by_disposition",
            "by_validation_status",
            "by_scoring_role",
        ):
            items = sorted(items)
        body = ", ".join(f"{k}: {v}" for k, v in items)
        lines.append(f"* **{title}:** {body}")
    lines += [
        "",
        "Validation levels: **NOT_TESTED** no check or no test; **UNIT_TESTED** unit "
        "tests only; **FIXTURE_VALIDATED** pre-declared synthetic fixture expectations "
        "met by the crawl-extract-feature harness; **PIPELINE_VALIDATED** those "
        "expectations also met through the application service and HTTP API "
        "(tests/validation/test_app_pipeline.py); **REAL_PAGE_VALIDATED** and "
        "**OUTCOME_VALIDATED** need a labelled real-world corpus and outcome data, "
        "which do not exist, so no feature is at those levels. "
        "Validation status codes: **V0** not implemented; **V1** implemented and "
        "unit-tested only; **V2** implemented and evaluated against pre-declared "
        "synthetic fixtures. **V3** (diagnostic accuracy benchmarked on labelled real "
        "pages) has not been reached by any feature. No feature has a demonstrated AI-"
        "visibility or business outcome.",
        "",
        "### Register",
        "",
        "| ID | Name | Status | Implementation | Validation level | Disposition | Scoring role | Confidence | Claim strength |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['feature_id']} | {r['name']} | {r['implementation_status']} | "
            f"{r['implementation_level']} | {r['validation_level']} | {r['disposition_code']} | "
            f"{r['scoring_role']} | {r['assessment_confidence']} | {r['claim_strength'].split(':')[0].split(',')[0]} |"
        )
    lines += [
        "",
        "### Threshold register",
        "",
        "| Setting | Default | Basis | Note |",
        "|---|---|---|---|",
    ]
    config = FeatureConfig()
    for key in FeatureConfig.model_fields:
        value = json.dumps(getattr(config, key), default=list)
        basis, note = THRESHOLDS[key]
        shown = value if len(value) < 60 else value[:57] + "..."
        lines.append(f"| `{key}` | `{shown}` | {basis} | {note} |")
    lines += ["", "### Per-feature assessment", ""]
    for r in rows:
        lines += [
            f"#### {r['feature_id']} {r['name']}",
            "",
            f"* **Disposition:** {r['disposition']} (confidence in this assessment: {r['assessment_confidence']})",
            f"* **Status / location:** {r['implementation_status']} · `{r['source_location']}` · {r['validation_status']}",
            f"* **Purpose:** {r['purpose']}",
            f"* **Claimed outcome ({r['benefit_class']}; {r['claim_strength']}):** {r['claimed_outcome']}",
            f"* **Configuration / threshold:** {r['default_configuration']} — basis: {r['threshold_basis']}",
            f"* **Scoring:** {r['scoring_role']}",
            f"* **Possible false positives:** {r['potential_false_positives']}",
            f"* **Possible false negatives:** {r['potential_false_negatives']}",
            f"* **Missing evidence:** {r['missing_evidence_behavior']}",
            f"* **Overlap:** {r['overlap_or_duplication']}",
            f"* **Discriminates / actionable:** {r['discriminates_valid_from_invalid']} / {r['supports_actionable_recommendation']}",
            f"* **Tests:** {r['existing_tests']}",
            f"* **Gaps:** {r['coverage_gaps']}",
            f"* **Follow-up:** {r['required_follow_up']}",
            "",
        ]
    lines.append(END)
    return "\n".join(lines)


def levels_json(rows: list[dict[str, str]]) -> str:
    """The shipped per-feature levels read by the API (geoptimiser.validation.levels)."""
    keep = ("feature_id", "implementation_level", "validation_level", "disposition_code",
            "validation_status", "threshold_basis", "claim_strength", "scoring_role",
            "assessment_confidence", "required_follow_up")  # fmt: skip
    document = {
        "generated_by": "python -m geoptimiser.validation.matrix --write",
        "summary": summary_counts(rows),
        "features": [{k: r[k] for k in keep} for r in rows],
    }
    return json.dumps(document, indent=1, sort_keys=False) + "\n"


def splice(document: str, generated: str) -> str:
    if BEGIN in document and END in document:
        head = document.split(BEGIN)[0]
        tail = document.split(END, 1)[1]
        return head + generated + tail
    return document.rstrip("\n") + "\n\n" + generated + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or check the feature matrix.")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    rows = build_rows()
    problems = completeness_problems(rows)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    docs = ROOT / "docs" / "validation"
    csv_path = docs / "feature_validation_matrix.csv"
    md_path = docs / "GEOPTIMISER_FEATURE_AUDIT.md"
    new_csv = to_csv(rows)
    new_md = splice(
        md_path.read_text(encoding="utf-8") if md_path.exists() else "",
        generated_markdown(rows),
    )
    new_levels = levels_json(rows)
    if args.write:
        docs.mkdir(parents=True, exist_ok=True)
        csv_path.write_text(new_csv, encoding="utf-8")
        md_path.write_text(new_md, encoding="utf-8")
        LEVELS_PATH.write_text(new_levels, encoding="utf-8")
        print(
            f"wrote {csv_path.relative_to(ROOT)}, {md_path.relative_to(ROOT)} and "
            f"{LEVELS_PATH.relative_to(ROOT)}"
        )
        return 0
    stale = []
    if (
        not LEVELS_PATH.exists()
        or LEVELS_PATH.read_text(encoding="utf-8") != new_levels
    ):
        stale.append(LEVELS_PATH.name)
    if not csv_path.exists() or csv_path.read_text(encoding="utf-8") != new_csv:
        stale.append(csv_path.name)
    if not md_path.exists() or md_path.read_text(encoding="utf-8") != new_md:
        stale.append(md_path.name)
    if stale:
        print(f"stale (rerun with --write): {', '.join(stale)}", file=sys.stderr)
        return 1
    print(f"ok: {len(rows)} features, matrix and audit document are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
