"""Compare a fixture run with the expectations declared in its spec."""

from collections import defaultdict
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from geoptimiser.schemas import FeatureResult, Finding
from geoptimiser.validation.metrics import BinaryCounts
from geoptimiser.validation.runner import FixtureRun
from geoptimiser.validation.spec import FeatureExpectation, ScoreExpectation


@dataclass(frozen=True)
class ExpectationResult:
    fixture: str
    kind: str  # feature | site_feature | finding | score | recommendation
    subject: str
    expected: str
    actual: str
    ok: bool
    detail: str = ""


@dataclass
class FixtureEvaluation:
    fixture: str
    results: list[ExpectationResult] = field(default_factory=list)
    counts: dict[str, BinaryCounts] = field(default_factory=dict)
    abstained: dict[str, dict[str, int]] = field(default_factory=dict)
    # (expected status, actual status) for every feature expectation: the full
    # confusion over result states, not only pass/fail.
    state_pairs: list[tuple[str, str]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.ok for r in self.results)

    @property
    def failures(self) -> list[ExpectationResult]:
        return [r for r in self.results if not r.ok]


def _path(url: str | None) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    return parts.path + (f"?{parts.query}" if parts.query else "")


def _problems(result: FeatureResult, exp: FeatureExpectation) -> list[str]:
    out: list[str] = []
    if result.status != exp.status:
        out.append(f"status {result.status!r}, expected {exp.status!r}")
    text = (result.explanation or "").lower()
    out += [
        f"explanation lacks {s!r}"
        for s in exp.explanation_contains
        if s.lower() not in text
    ]
    out += [
        f"explanation has {s!r}" for s in exp.explanation_excludes if s.lower() in text
    ]
    limits = " ".join(result.limitations).lower()
    out += [
        f"limitations lack {s!r}"
        for s in exp.limitation_contains
        if s.lower() not in limits
    ]
    if exp.severity is not None and result.severity != exp.severity:
        out.append(f"severity {result.severity!r}, expected {exp.severity!r}")
    return out


def _tally(ev: FixtureEvaluation, feature_id: str, expected: str, actual: str) -> None:
    """Confusion counts for presence/validity checks; the positive class is `fail`."""
    if expected not in ("pass", "fail"):
        return
    counts = ev.counts.get(feature_id, BinaryCounts())
    if actual in ("pass", "fail", "warning"):
        predicted_fail = actual == "fail"
        if expected == "fail":
            counts += BinaryCounts(tp=int(predicted_fail), fn=int(not predicted_fail))
        else:
            counts += BinaryCounts(fp=int(predicted_fail), tn=int(not predicted_fail))
    else:
        abstain = ev.abstained.setdefault(feature_id, defaultdict(int))
        abstain[f"expected_{expected}"] += 1
    ev.counts[feature_id] = counts


def _finding_text(finding: Finding) -> str:
    return " ".join(
        [
            finding.title,
            finding.description,
            finding.remediation or "",
            *finding.limitations,
            *finding.verification_criteria,
        ]
    )


def _score_problems(group: object, exp: ScoreExpectation) -> list[str]:
    out = []
    if exp.reportable is not None and group.reportable != exp.reportable:  # type: ignore[attr-defined]
        out.append(f"reportable={group.reportable}, expected {exp.reportable}")  # type: ignore[attr-defined]
    if exp.score is not None:
        actual = group.score  # type: ignore[attr-defined]
        if actual is None or abs(actual - exp.score) > exp.score_tolerance:
            out.append(f"score={actual}, expected {exp.score}")
    if exp.feature_coverage is not None:
        actual = group.feature_coverage  # type: ignore[attr-defined]
        if actual is None or abs(actual - exp.feature_coverage) > 0.0005:
            out.append(f"feature_coverage={actual}, expected {exp.feature_coverage}")
    return out


def evaluate_fixture(fixture: FixtureRun) -> FixtureEvaluation:
    spec, exp = fixture.spec, fixture.spec.expect
    ev = FixtureEvaluation(spec.id)

    def add(
        kind: str, subject: str, expected: str, actual: str, problems: list[str]
    ) -> None:
        ev.results.append(
            ExpectationResult(
                spec.id,
                kind,
                subject,
                expected,
                actual,
                not problems,
                "; ".join(problems),
            )
        )

    by_page: dict[tuple[str, str], list[FeatureResult]] = defaultdict(list)
    by_feature: dict[str, list[FeatureResult]] = defaultdict(list)
    for r in fixture.run.results:
        by_page[(r.feature_id, _path(r.subject_url))].append(r)
        by_feature[r.feature_id].append(r)

    for path, features in exp.pages.items():
        for feature_id, want in features.items():
            found = by_page.get((feature_id, path), [])
            subject = f"{feature_id} {path}"
            if not found:
                add(
                    "feature",
                    subject,
                    want.status,
                    "(no result)",
                    ["no result for this page"],
                )
                continue
            actual = found[0]
            ev.state_pairs.append((want.status, actual.status))
            add("feature", subject, want.status, actual.status, _problems(actual, want))
            _tally(ev, feature_id, want.status, actual.status)

    for feature_id, want in exp.site.items():
        found = by_feature.get(feature_id, [])
        if not found:
            add("site_feature", feature_id, want.status, "(no result)", ["no result"])
            continue
        trials = [(_problems(r, want), r) for r in found]
        best = next((t for t in trials if not t[0]), trials[0])
        ev.state_pairs.append((want.status, best[1].status))
        add("site_feature", feature_id, want.status, best[1].status, best[0])

    findings = {f.finding_id: f for f in fixture.diagnosis.findings}
    for fid in exp.findings.present:
        add(
            "finding",
            fid,
            "present",
            "present" if fid in findings else "absent",
            [] if fid in findings else ["finding missing"],
        )
    for fid in exp.findings.absent:
        add(
            "finding",
            fid,
            "absent",
            "present" if fid in findings else "absent",
            ["finding raised although it must not be"] if fid in findings else [],
        )
    for fid, severity in exp.findings.severity.items():
        got = findings[fid].severity if fid in findings else "(absent)"
        add(
            "finding",
            f"{fid} severity",
            severity,
            got,
            [] if got == severity else [f"severity {got}"],
        )
    for fid, fragments in exp.findings.text_contains.items():
        text = _finding_text(findings[fid]).lower() if fid in findings else ""
        missing = [s for s in fragments if s.lower() not in text]
        add(
            "finding",
            f"{fid} text",
            "contains " + ", ".join(fragments),
            "ok" if not missing else "missing",
            [f"lacks {s!r}" for s in missing],
        )
    for fid, fragments in exp.findings.text_excludes.items():
        text = _finding_text(findings[fid]).lower() if fid in findings else ""
        present = [s for s in fragments if s.lower() in text]
        add(
            "finding",
            f"{fid} text",
            "excludes " + ", ".join(fragments),
            "ok" if not present else "present",
            [f"contains {s!r}" for s in present],
        )

    rec_text = " ".join(
        " ".join([r.title, r.rationale, r.proposed_change, *r.verification_plan])
        for r in fixture.recommendations.recommendations
    ).lower()
    for s in exp.recommendation_excludes:
        add(
            "recommendation",
            f"excludes {s!r}",
            "absent",
            "present" if s.lower() in rec_text else "absent",
            [f"recommendation text contains {s!r}"] if s.lower() in rec_text else [],
        )
    for s in exp.recommendation_includes:
        add(
            "recommendation",
            f"includes {s!r}",
            "present",
            "present" if s.lower() in rec_text else "absent",
            [] if s.lower() in rec_text else [f"recommendation text lacks {s!r}"],
        )

    scores = fixture.run.scores
    if exp.scores.overall is not None:
        problems = _score_problems(scores.overall, exp.scores.overall)
        add(
            "score",
            "overall",
            str(exp.scores.overall.model_dump(exclude_none=True)),
            f"score={scores.overall.score} reportable={scores.overall.reportable}",
            problems,
        )
    cats = {c.key: c for c in scores.categories}
    for code, want_score in exp.scores.categories.items():
        group = cats[code]
        add(
            "score",
            f"category {code}",
            str(want_score.model_dump(exclude_none=True)),
            f"score={group.score} reportable={group.reportable}",
            _score_problems(group, want_score),
        )
    contributes = {
        f.feature_id: f.scored and getattr(f, "contributes", True)
        for f in scores.features
    }
    for fid in exp.scores.not_contributing:
        ok = not contributes.get(fid, True)
        add(
            "score",
            f"{fid} contributes",
            "no",
            str(contributes.get(fid, True)).lower(),
            [] if ok else ["feature still contributes to the aggregate"],
        )
    for fid in exp.scores.contributing:
        ok = contributes.get(fid, True)
        add(
            "score",
            f"{fid} contributes",
            "yes",
            str(contributes.get(fid, True)).lower(),
            [] if ok else ["feature is excluded from the aggregate"],
        )
    return ev
